"""Fonte de dados do índice.

`FonteCar` separa o Radar da origem dos dados. Hoje a implementação usa os serviços
públicos; em produção, o mesmo contrato pode ler uma réplica interna do SICAR.
"""
from __future__ import annotations

import gzip
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol

from . import sicar

USER_AGENT = "car-em-recorte-indice/0.5 (prototipo InovaCAR; sincronizacao controlada)"
PAGE_SIZE = 5000
CHANGE_PAGE_SIZE = 1000
Transport = Callable[[str, bytes | None], tuple[int, bytes, int]]


class FonteBloqueada(Exception):
    """A fonte recusou o acesso; a rotina deve parar imediatamente."""


class FonteIndisponivel(Exception):
    """Falha temporária ao consultar a fonte."""


class OrcamentoEsgotado(Exception):
    """O limite de chamadas da execução foi atingido."""


@dataclass(frozen=True)
class Municipio:
    ibge: int
    nome: str
    lon: float | None = None
    lat: float | None = None


class FonteCar(Protocol):
    chamadas: int
    bytes_recebidos: int

    def municipios(self, uf: str) -> list[Municipio]: ...
    def cadastro_municipio(self, uf: str, ibge: int) -> list[dict[str, Any]]: ...
    def total_municipio(self, uf: str, ibge: int) -> int: ...
    def total_alterados(self, uf: str, desde: date) -> int: ...
    def alterados(self, uf: str, desde: date, apos: str | None) -> list[dict[str, Any]]: ...
    def codigos_recompor(self, uf: str, municipio: str | None = None) -> set[str]: ...
    def sobreposicoes(self, uf: str, municipio: str | None = None) -> dict[str, set[str]]: ...
    def retificacoes(self, uf: str, municipio: str) -> dict[str, int]: ...


def _default_transport(url: str, data: bytes | None) -> tuple[int, bytes, int]:
    """Devolve status, corpo descompactado e bytes realmente trafegados."""
    request = urllib.request.Request(
        url, data=data, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"}
    )
    try:
        with urllib.request.urlopen(
            request, timeout=sicar.TIMEOUT_SECONDS, context=sicar.TLS_CONTEXT
        ) as response:
            raw = response.read()
            encoded = response.headers.get("Content-Encoding") == "gzip"
            status = response.status
    except urllib.error.HTTPError as exc:
        body = exc.read()
        return exc.code, body, len(body)
    except (OSError, TimeoutError) as exc:
        raise FonteIndisponivel(str(exc)) from exc
    return status, gzip.decompress(raw) if encoded else raw, len(raw)


class ServicosPublicosCar:
    """Consulta WFS públicos, uma chamada por vez e dentro do orçamento recebido."""

    def __init__(
        self,
        intervalo: float = 10.0,
        limite_chamadas: int = 600,
        transport: Transport = _default_transport,
        dormir: Callable[[float], None] = time.sleep,
    ) -> None:
        self.intervalo = intervalo
        self.limite_chamadas = limite_chamadas
        self.transport = transport
        self.dormir = dormir
        self.chamadas = 0
        self.bytes_recebidos = 0

    def _chamar(self, url: str, data: bytes | None = None) -> bytes:
        if self.chamadas >= self.limite_chamadas:
            raise OrcamentoEsgotado(f"Limite de {self.limite_chamadas} chamadas atingido.")
        if self.chamadas:
            self.dormir(self.intervalo)
        self.chamadas += 1
        status, body, trafegados = self.transport(url, data)
        self.bytes_recebidos += trafegados
        if status in {401, 403, 429} or b"Acesso negado" in body[:2000]:
            raise FonteBloqueada(f"A fonte respondeu {status} em {url.split('?')[0]}.")
        if status >= 400:
            raise FonteIndisponivel(f"A fonte respondeu {status} em {url.split('?')[0]}.")
        return body

    def _wfs(self, url: str, **params: Any) -> dict[str, Any]:
        payload = {
            "service": "WFS",
            "version": "2.0.0",
            "request": "GetFeature",
            "outputFormat": "application/json",
            **params,
        }
        body = self._chamar(url, urllib.parse.urlencode(payload).encode("utf-8"))
        try:
            result = json.loads(body)
        except ValueError as exc:
            raise FonteIndisponivel(f"Resposta inesperada: {body[:160]!r}") from exc
        if "features" not in result:
            raise FonteIndisponivel("Resposta sem a lista de feições.")
        return result

    def _hits(self, url: str, type_name: str, cql: str) -> int:
        payload = {
            "service": "WFS",
            "version": "2.0.0",
            "request": "GetFeature",
            "typeNames": type_name,
            "resultType": "hits",
            "cql_filter": cql,
        }
        body = self._chamar(url, urllib.parse.urlencode(payload).encode("utf-8"))
        match = re.search(rb'numberMatched="(\d+)"', body)
        if not match:
            raise FonteIndisponivel("A fonte não informou a quantidade de registros.")
        return int(match.group(1))

    def _codigos(self, layer: str, condicao: str, campos: str = "cod_imovel") -> list[dict[str, Any]]:
        """Percorre uma camada por código, sem deslocamentos profundos."""
        rows: list[dict[str, Any]] = []
        last: str | None = None
        while True:
            cql = condicao if last is None else f"{condicao} AND cod_imovel > {sicar.quote(last)}"
            features = self._wfs(
                sicar.CONSULTA_WFS,
                typeNames=f"consulta_publica:{layer}",
                propertyName=campos,
                cql_filter=cql,
                sortBy="cod_imovel",
                count=PAGE_SIZE,
            )["features"]
            rows.extend(feature["properties"] for feature in features)
            if len(features) < PAGE_SIZE:
                return rows
            last = features[-1]["properties"]["cod_imovel"]

    @staticmethod
    def _filtro_uf(uf: str, municipio: str | None) -> str:
        cql = f"uf={sicar.quote(uf)}"
        return f"{cql} AND municipio={sicar.quote(municipio)}" if municipio else cql

    def municipios(self, uf: str) -> list[Municipio]:
        body = self._chamar(f"{sicar.CONSULTA_API}/state/getCitiesByUf/{uf}")
        items = []
        for row in json.loads(body):
            bounds = sicar._bounds(row.get("bounderBox"))
            lon = (bounds[0] + bounds[2]) / 2 if bounds else None
            lat = (bounds[1] + bounds[3]) / 2 if bounds else None
            items.append(Municipio(int(row["id"]), row["name"], lon, lat))
        return sorted(items, key=lambda item: sicar.plain(item.nome))

    def cadastro_municipio(self, uf: str, ibge: int) -> list[dict[str, Any]]:
        """Lê o município inteiro; uma resposta parcial nunca pode parecer completa."""
        items: list[dict[str, Any]] = []
        base = f"cod_municipio_ibge={int(ibge)}"
        last: str | None = None
        while True:
            cql = base if last is None else f"{base} AND cod_imovel > {sicar.quote(last)}"
            features = self._wfs(
                sicar.SICAR_WFS,
                typeNames=sicar.property_layer(uf),
                propertyName=sicar.PROPERTY_FIELDS,
                cql_filter=cql,
                sortBy="cod_imovel",
                count=PAGE_SIZE,
            )["features"]
            items.extend(sicar.normalize_property({**feature, "geometry": None}) for feature in features)
            if len(features) < PAGE_SIZE:
                return items
            last = features[-1]["properties"]["cod_imovel"]

    def total_municipio(self, uf: str, ibge: int) -> int:
        return self._hits(sicar.SICAR_WFS, sicar.property_layer(uf), f"cod_municipio_ibge={int(ibge)}")

    def total_alterados(self, uf: str, desde: date) -> int:
        return self._hits(
            sicar.SICAR_WFS, sicar.property_layer(uf), f"data_atualizacao >= '{desde.isoformat()}'"
        )

    def alterados(self, uf: str, desde: date, apos: str | None) -> list[dict[str, Any]]:
        cql = f"data_atualizacao >= '{desde.isoformat()}'"
        if apos:
            cql += f" AND cod_imovel > {sicar.quote(apos)}"
        features = self._wfs(
            sicar.SICAR_WFS,
            typeNames=sicar.property_layer(uf),
            propertyName=sicar.PROPERTY_FIELDS,
            cql_filter=cql,
            sortBy="cod_imovel",
            count=CHANGE_PAGE_SIZE,
        )["features"]
        return [sicar.normalize_property({**feature, "geometry": None}) for feature in features]

    def codigos_recompor(self, uf: str, municipio: str | None = None) -> set[str]:
        codes: set[str] = set()
        for layer in sicar.RESTORE_LAYERS:
            rows = self._codigos(layer, self._filtro_uf(uf, municipio))
            codes.update(row["cod_imovel"] for row in rows if row.get("cod_imovel"))
        return codes

    def sobreposicoes(self, uf: str, municipio: str | None = None) -> dict[str, set[str]]:
        found: dict[str, set[str]] = {key: set() for key in sicar.OVERLAP_LABELS}
        for layer in ("iru", "ast", "pct"):
            for field in sicar.OVERLAP_LABELS:
                rows = self._codigos(layer, f"{self._filtro_uf(uf, municipio)} AND {field} > 0")
                found[field].update(row["cod_imovel"] for row in rows if row.get("cod_imovel"))
        return found

    def retificacoes(self, uf: str, municipio: str) -> dict[str, int]:
        rows = self._codigos(
            "area_consolidada",
            self._filtro_uf(uf, municipio),
            "cod_imovel,nu_retificacao",
        )
        result: dict[str, int] = {}
        for row in rows:
            code = row.get("cod_imovel")
            if code:
                result[code] = max(result.get(code, 0), int(row.get("nu_retificacao") or 0))
        return result
