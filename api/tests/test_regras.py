"""Testes sem rede das regras, do assistente e da proteção da fonte."""
import json
import unittest
from datetime import date

from app import assistente, classificacao, credito, fonte, indice, sicar

HOJE = date(2026, 11, 18)
MUNICIPIOS = [{"ibge": 2105401, "municipio": "Itapecuru Mirim"}, {"ibge": 2100055, "municipio": "Açailândia"}]


def linha(**campos):
    base = {"status": "AT", "condicao_grupo": "aguardando_analise", "condicao": "Aguardando análise",
            "data_criacao": date(2015, 1, 1), "area_ha": 50.0, "modulos": 1.0, "sobreposicoes": []}
    return {**base, **campos}


class Classificacao(unittest.TestCase):
    def test_fila_longa_soma_pesos(self):
        perfis, prioridade = classificacao.classificar(linha(), HOJE)
        self.assertEqual(perfis, ["sem_analise", "fila_5_anos", "fila_10_anos"])
        self.assertEqual(prioridade, 35)

    def test_cancelado_nao_entra_na_fila(self):
        perfis, prioridade = classificacao.classificar(linha(status="CA", condicao_grupo="cancelado"), HOJE)
        self.assertEqual(perfis, ["status_cancelado"])
        self.assertEqual(prioridade, 0)

    def test_sobreposicao_e_app(self):
        perfis, _ = classificacao.classificar(
            linha(data_criacao=date(2026, 1, 1), tem_app_recompor=True, sobreposicoes=["sobreposicao_area_embargada"]), HOJE)
        self.assertIn("app_recompor", perfis)
        self.assertIn("sobre_embargo", perfis)

    def test_prioridade_tem_teto(self):
        campos = ["sobreposicao_area_embargada", "sobreposicao_area_indigena", "sobreposicao_unidade_conservacao",
                  "sobreposicao_quilombo", "sobreposicao_terras_da_uniao"]
        self.assertEqual(classificacao.classificar(linha(sobreposicoes=campos, modulos=20), HOJE)[1], 100)

    def test_todo_perfil_explica_motivo_e_fonte(self):
        for item in classificacao.catalogo():
            self.assertTrue(item["descricao"] and item["fonte"])


class Hash(unittest.TestCase):
    item = {"ind_status": "AT", "ind_tipo": "IRU", "des_condic": "x", "num_area": 1.5, "mod_fiscal": 1,
            "municipio": "A", "cod_municipio_ibge": 1, "data_criacao": "2020-01-01", "data_atualizacao": "2026-01-01"}

    def test_data_de_atualizacao_nao_conta_como_mudanca(self):
        self.assertEqual(indice.hash_cadastro(self.item), indice.hash_cadastro({**self.item, "data_atualizacao": "2026-11-18"}))

    def test_condicao_conta_como_mudanca(self):
        self.assertNotEqual(indice.hash_cadastro(self.item), indice.hash_cadastro({**self.item, "des_condic": "y"}))


class Assistente(unittest.TestCase):
    def interpretar(self, texto):
        return assistente.interpretar(texto, "MA", MUNICIPIOS)

    def test_contagem_com_tempo(self):
        item = self.interpretar("Quantos imóveis estão sem análise há mais de 5 anos?")
        self.assertEqual(item.intencao, "contagem")
        self.assertEqual(item.filtro, {"perfis": ["sem_analise"], "anos_min": 5})

    def test_sem_analise_nao_vira_em_analise(self):
        self.assertNotIn("condicao", self.interpretar("imóveis sem análise").filtro)
        self.assertEqual(self.interpretar("imóveis em análise").filtro["condicao"], "em_analise")

    def test_municipio_sem_acento_limite_e_ordem(self):
        item = self.interpretar("mostre os 7 mais antigos na fila em acailandia")
        self.assertEqual((item.ibge, item.limite, item.filtro["ordem"]), (2100055, 7, "antiguidade"))

    def test_area_com_milhar(self):
        self.assertEqual(self.interpretar("acima de 1.000 hectares").filtro["area_min"], 1000)
        self.assertEqual(self.interpretar("menos de 2 mil hectares").filtro["area_max"], 2000)

    def test_ranking_e_outro_estado(self):
        self.assertEqual(self.interpretar("quais municípios têm mais APP a recompor").intencao, "ranking")
        self.assertEqual(self.interpretar("imóveis cancelados no Pará").uf_pedida, "PA")

    def test_pergunta_fora_do_tema(self):
        self.assertEqual(self.interpretar("qual a capital da França?").entendido, [])

    def test_analisados_no_ultimo_mes(self):
        filtro = self.interpretar("imóveis analisados no último mês").filtro
        self.assertIn("analisado_desde", filtro)
        self.assertGreaterEqual((date.today() - date.fromisoformat(filtro["analisado_desde"])).days, 28)

    def test_continuacao_mantem_filtros_anteriores(self):
        item = self.interpretar("e só em Itapecuru Mirim")
        assistente._mesclar(item, {"filtros": {"perfis": ["sem_analise"], "anos_min": 5}}, MUNICIPIOS)
        self.assertEqual((item.ibge, item.filtro["perfis"], item.filtro["anos_min"]), (2105401, ["sem_analise"], 5))

    def test_definicao_vem_da_central(self):
        achado = assistente.definir("o que é módulo fiscal?")
        self.assertEqual(achado["termo"].lower(), "módulo fiscal")
        self.assertIsNone(assistente.definir("o que é fotossíntese?"))


class Credito(unittest.TestCase):
    def test_pontos_ordenados_por_nivel(self):
        pontos = credito.pontos(["sem_analise", "app_recompor", "status_cancelado"])
        self.assertEqual([p["nivel"] for p in pontos], ["alta", "atencao", "info"])
        self.assertTrue(all(p["fonte"] for p in pontos))

    def test_resultado_pelo_pior_ponto(self):
        self.assertEqual(credito._resultado({"pontos": credito.pontos(["sobre_embargo", "app_recompor"])}), "atencao_alta")
        self.assertEqual(credito._resultado({"pontos": credito.pontos(["app_recompor"])}), "atencao")
        self.assertEqual(credito._resultado({"pontos": credito.pontos(["analisado_conforme"])}), "sem_pontos")

    def test_fora_do_indice_avisa_indicadores_nao_verificados(self):
        pontos = credito.pontos(["sem_analise"], indicadores_ambientais=False)
        self.assertIn("indicadores_nao_verificados", [p["codigo"] for p in pontos])


def transporte(respostas, pedidos=None):
    fila = list(respostas)

    def chamar(url, data):
        if pedidos is not None:
            pedidos.append((data or b"").decode())
        status, corpo = fila.pop(0)
        corpo = corpo if isinstance(corpo, bytes) else json.dumps(corpo).encode()
        return status, corpo, len(corpo)

    return chamar


def pagina(codigos):
    return {"features": [{"properties": {"cod_imovel": c}} for c in codigos]}


class Fonte(unittest.TestCase):
    def nova(self, respostas, pedidos=None, limite=10, esperas=None):
        return fonte.ServicosPublicosCar(1, limite, transporte(respostas, pedidos), (esperas if esperas is not None else []).append)

    def test_403_e_429_bloqueiam(self):
        for status in (403, 429):
            with self.assertRaises(fonte.FonteBloqueada):
                self.nova([(status, b"")]).total_municipio("MA", 1)

    def test_pagina_de_acesso_negado_bloqueia(self):
        with self.assertRaises(fonte.FonteBloqueada):
            self.nova([(200, b"<h1>Acesso negado</h1>")]).total_municipio("MA", 1)

    def test_erro_500_e_temporario(self):
        with self.assertRaises(fonte.FonteIndisponivel):
            self.nova([(500, b"")]).total_municipio("MA", 1)

    def test_orcamento_impede_nova_chamada(self):
        origem = self.nova([(200, b'numberMatched="1"')], limite=1)
        origem.total_municipio("MA", 1)
        with self.assertRaises(fonte.OrcamentoEsgotado):
            origem.total_municipio("MA", 1)
        self.assertEqual(origem.chamadas, 1)

    def test_municipio_com_varias_paginas_fica_completo(self):
        antigo = fonte.PAGE_SIZE
        fonte.PAGE_SIZE = 2
        self.addCleanup(setattr, fonte, "PAGE_SIZE", antigo)
        pedidos, esperas = [], []
        origem = self.nova([(200, pagina(["A", "B"])), (200, pagina(["C"]))], pedidos, esperas=esperas)
        self.assertEqual([i["cod_imovel"] for i in origem.cadastro_municipio("MA", 1)], ["A", "B", "C"])
        self.assertIn("cod_imovel+%3E+%27B%27", pedidos[1])
        self.assertEqual(esperas, [1])

    def test_nao_pede_geometria(self):
        pedidos = []
        self.nova([(200, pagina([]))], pedidos).cadastro_municipio("MA", 1)
        self.assertNotIn("geo_area_imovel", pedidos[0])


if __name__ == "__main__":
    unittest.main()
