"""Testes da sincronização em um esquema temporário do banco, com fonte simulada."""
import os
import unittest
import uuid
from datetime import date, timedelta

import psycopg

from app import indice, radar, sicar, sync_indice
from app.fonte import CHANGE_PAGE_SIZE, FonteBloqueada, FonteIndisponivel, Municipio, OrcamentoEsgotado

UF = "MA"


def imovel(codigo, ibge, condicao="Aguardando análise", atualizado="2026-11-18T12:00:00Z"):
    return sicar.normalize_property({"geometry": None, "properties": {
        "cod_imovel": codigo, "status_imovel": "AT", "dat_criacao": "2015-01-01T12:00:00Z",
        "data_atualizacao": atualizado, "area": 10.0, "condicao": condicao, "uf": UF,
        "municipio": f"M{ibge}", "cod_municipio_ibge": ibge, "m_fiscal": 1.0, "tipo_imovel": "IRU"}})


class FonteFalsa:
    def __init__(self, base, limite=100, erro=None):
        self.base, self.limite, self.erro = base, limite, erro
        self.chamadas = self.bytes_recebidos = 0
        self.lidos, self.alterados_lista, self.total_mudancas = [], [], 0

    def _gastar(self):
        if self.chamadas >= self.limite:
            raise self.erro or OrcamentoEsgotado("limite")
        self.chamadas += 1
        self.bytes_recebidos += 10

    def municipios(self, uf):
        return [Municipio(ibge, f"M{ibge}") for ibge in self.base]

    def cadastro_municipio(self, uf, ibge):
        self._gastar()
        self.lidos.append(ibge)
        return list(self.base[ibge])

    def total_municipio(self, uf, ibge):
        self._gastar()
        return len(self.base[ibge])

    def total_alterados(self, uf, desde):
        self._gastar()
        return self.total_mudancas

    def alterados(self, uf, desde, apos):
        self._gastar()
        restantes = [i for i in self.alterados_lista if not apos or i["cod_imovel"] > apos]
        return restantes[:CHANGE_PAGE_SIZE]


class Sincronizacao(unittest.TestCase):
    def setUp(self):
        os.environ["SYNC_SEM_ESPERA"] = "1"
        self.esquema = f"teste_{uuid.uuid4().hex[:10]}"
        self.conn = psycopg.connect(sicar.DATABASE_URL)
        self.conn.execute(f"CREATE SCHEMA {self.esquema}")
        self.conn.execute(f"SET search_path TO {self.esquema}, public")
        self.conn.commit()
        indice.criar_esquema(self.conn)
        self.conn.commit()
        self.base = {1: [imovel("A", 1), imovel("B", 1)], 2: [imovel("C", 2)], 3: [imovel("D", 3)]}

    def tearDown(self):
        self.conn.rollback()
        self.conn.execute(f"DROP SCHEMA {self.esquema} CASCADE")
        self.conn.commit()
        self.conn.close()

    def valor(self, sql, *args):
        return self.conn.execute(sql, args).fetchone()[0]

    def carga(self, origem):
        return sync_indice.carregar_municipios(self.conn, origem, UF, "carga")

    def test_interrompe_no_orcamento_e_retoma_sem_refazer(self):
        primeira = FonteFalsa(self.base, limite=2)
        self.assertEqual(self.carga(primeira)["status"], "orcamento_esgotado")
        self.assertIsNone(self.valor("SELECT carga_concluida_em FROM sync_estado"))
        segunda = FonteFalsa(self.base)
        self.assertEqual(self.carga(segunda)["status"], "concluida")
        self.assertEqual(segunda.lidos, [3])
        self.assertEqual(self.valor("SELECT count(*) FROM indice_imovel"), 4)
        self.assertIsNotNone(self.valor("SELECT carga_concluida_em FROM sync_estado"))

    def test_bloqueio_para_e_pausa(self):
        origem = FonteFalsa(self.base, limite=1, erro=FonteBloqueada("403"))
        self.assertEqual(self.carga(origem)["status"], "bloqueada")
        self.assertEqual(origem.chamadas, 1)
        with self.assertRaises(sync_indice.RotinaPausada):
            self.carga(FonteFalsa(self.base))

    def test_falhas_seguidas_param(self):
        origem = FonteFalsa(self.base, limite=0, erro=FonteIndisponivel("500"))
        self.assertEqual(self.carga(origem)["status"], "falhou")
        self.assertIsNotNone(self.valor("SELECT pausado_ate FROM sync_estado"))

    def test_conferencia_detecta_remocao(self):
        self.carga(FonteFalsa(self.base))
        self.base[1] = [imovel("A", 1)]
        resultado = sync_indice.conferir_totais(self.conn, FonteFalsa(self.base), UF)
        self.assertEqual(resultado["removidos"], 1)
        self.assertEqual(self.valor("SELECT count(*) FROM indice_imovel WHERE cod_imovel = 'B'"), 0)

    def test_diario_ignora_data_sem_mudanca_e_grava_mudanca_real(self):
        self.carga(FonteFalsa(self.base))
        origem = FonteFalsa(self.base)
        origem.total_mudancas = 2
        origem.alterados_lista = [imovel("A", 1, atualizado="2026-11-19T12:00:00Z"), imovel("C", 2, "Em análise")]
        resultado = sync_indice.sincronizar_diario(self.conn, origem, UF, date.today() + timedelta(days=1))
        self.assertEqual((resultado["alterados"], resultado["novos"]), (1, 0))
        self.assertEqual(self.valor("SELECT condicao_grupo FROM indice_imovel WHERE cod_imovel = 'C'"), "em_analise")

    def test_atualizacao_em_massa_vira_recarga_gradual(self):
        self.carga(FonteFalsa(self.base))
        hoje = date.today()
        origem = FonteFalsa(self.base)
        origem.total_mudancas = sync_indice.LIMITE_ALTERACOES + 1
        sync_indice.sincronizar_diario(self.conn, origem, UF, hoje)
        self.assertEqual(origem.chamadas, 1)
        self.assertEqual(self.valor("SELECT count(*) FROM sync_checkpoint WHERE ciclo = %s", f"recarga:{hoje:%Y-%m}"), 0)

    def test_resumo_e_snapshot(self):
        self.carga(FonteFalsa(self.base))
        self.assertEqual(indice.recalcular_uf(self.conn, UF)["imoveis"], 4)
        self.assertEqual(self.valor("SELECT (dados->>'sem_analise')::int FROM resumo_municipio WHERE ibge = 0"), 4)
        self.assertEqual(self.valor("SELECT sum(total)::int FROM snapshot_municipio"), 4)

    def test_historico_registra_mudanca_diaria_e_nao_a_carga(self):
        self.carga(FonteFalsa(self.base))
        self.assertEqual(self.valor("SELECT count(*) FROM historico_imovel"), 0)
        origem = FonteFalsa(self.base)
        origem.total_mudancas = 1
        origem.alterados_lista = [imovel("C", 2, "Analisado, em conformidade com a Lei nº 12.651/2012")]
        dia = date.today() + timedelta(days=1)
        sync_indice.sincronizar_diario(self.conn, origem, UF, dia)
        evento = self.conn.execute(
            "SELECT evento, condicao_anterior, condicao_nova, dia FROM historico_imovel WHERE cod_imovel = 'C'").fetchone()
        self.assertEqual(evento[:2], ("condicao", "aguardando_analise"))
        self.assertTrue(evento[2].startswith("analisado"))
        self.assertEqual(evento[3], dia)
        filtro = radar.FiltroFila(uf=UF, analisado_desde=dia - timedelta(days=30)).validar()
        where, valores = filtro.where()
        codigos = [l[0] for l in self.conn.execute(f"SELECT cod_imovel FROM indice_imovel WHERE {where}", valores)]
        self.assertEqual(codigos, ["C"])

    def test_limite_gravado_e_filtro_por_area_do_mapa(self):
        self.carga(FonteFalsa(self.base))
        quadrado = lambda x, y: {"type": "Polygon", "coordinates": [[[x, y], [x + .01, y], [x + .01, y + .01], [x, y + .01], [x, y]]]}
        gravados = indice.gravar_geometrias(self.conn, [("A", quadrado(-44.0, -3.0)), ("C", quadrado(-45.0, -4.0)), ("FORA", quadrado(-44.0, -3.0))])
        self.assertEqual(gravados, 2)
        self.assertEqual(self.valor("SELECT ST_SRID(geom) FROM geometria_imovel WHERE cod_imovel = 'A'"), 4674)
        filtro = radar.FiltroFila(uf=UF, bbox=(-44.1, -3.1, -43.9, -2.9)).validar()
        where, valores = filtro.where()
        codigos = [l[0] for l in self.conn.execute(f"SELECT cod_imovel FROM indice_imovel WHERE {where}", valores)]
        self.assertEqual(codigos, ["A"])
