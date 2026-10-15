"""Localizador de endereços de Rondonópolis - MT.

100% gratuito e sem chaves de API:
  - Nominatim (OpenStreetMap) para achar as coordenadas;
  - Leaflet + mapa do OpenStreetMap para exibir (ver templates/index.html);
  - ViaCEP SOMENTE quando a linha digitada contém um CEP.
"""
import json
import os
import re
import tempfile
import threading
import time
import unicodedata
from difflib import SequenceMatcher

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

load_dotenv()

app = Flask(__name__)

CIDADE, UF = "Rondonópolis", "MT"
# esquerda, topo, direita, base (lon, lat, lon, lat): caixa que envolve a área urbana
VIEWBOX = "-54.80,-16.35,-54.50,-16.60"
PAUSA_NOMINATIM = 1.1  # a política do servidor público pede no máximo 1 requisição por segundo
UA = "localizador-enderecos/1.0 ({})".format(
    os.environ.get("CONTATO_EMAIL", "defina CONTATO_EMAIL no .env")
)
CACHE_ARQ = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache.json")

# campos do OpenStreetMap que podem guardar o nome do bairro
CHAVES_BAIRRO = ("suburb", "neighbourhood", "quarter", "city_district")
# resultados que são regiões inteiras, não um endereço
TIPOS_AMPLOS = {"city", "state", "country", "county", "municipality", "region",
                "state_district", "town", "village"}

# abreviações aceitas em qualquer lugar do texto
ABREV = {
    "jd": "jardim", "jdm": "jardim", "vl": "vila", "pq": "parque",
    "res": "residencial", "cj": "conjunto", "conj": "conjunto",
    "hab": "habitacional", "ind": "industrial", "st": "setor",
    "sta": "santa", "sto": "santo", "cond": "condomínio", "dist": "distrito",
}
# abreviações de tipo de via, só valem na primeira palavra do logradouro
ABREV_TIPO = {
    "r": "Rua", "av": "Avenida", "al": "Alameda", "tv": "Travessa",
    "trav": "Travessa", "pc": "Praça", "pca": "Praça", "rod": "Rodovia",
    "est": "Estrada",
}
STOP = {"de", "da", "do", "das", "dos", "e"}

RE_CEP = re.compile(r"(?:cep\s*:?\s*)?(?<!\d)(\d{5})-?(\d{3})(?!\d)", re.I)
RE_NUMERO = re.compile(r"^(?:n[ºo°.]*\s*)?\d+[a-z]?$|^s/?n$")
RE_NUMERO_FINAL = re.compile(r",\s*(?:n[ºo°.]*\s*)?\d+[a-zA-Z]?\s*$")
RE_SEPARADOR = re.compile(r"\s*[,;\t]\s*|\s+-\s+")
IGNORAR_PARTE = {"mt", "mato grosso", "brasil", "brazil", "br"}

_nom_lock = threading.Lock()    # serializa as consultas ao Nominatim (1 por segundo)
_cache_lock = threading.Lock()  # protege o arquivo de cache
_ultimo = 0.0

try:
    with open(CACHE_ARQ, encoding="utf-8") as f:
        _cache = json.load(f)
except Exception:
    _cache = {}


def _salvar():
    """Grava o cache de forma atômica (arquivo temporário + troca)."""
    with _cache_lock:
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(CACHE_ARQ), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(_cache, f, ensure_ascii=False)
            os.replace(tmp, CACHE_ARQ)
        except Exception:
            if os.path.exists(tmp):
                os.remove(tmp)


def norm(s):
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower().strip()


def expandir(texto, tipo=False):
    """Troca abreviações (Jd, Vl, Av...) pelo nome por extenso, mantendo os acentos."""
    tokens = [t for t in re.split(r"[\s.]+", (texto or "").strip()) if t]
    saida = []
    for n, t in enumerate(tokens):
        k = norm(t)
        if tipo and n == 0 and k in ABREV_TIPO:
            saida.append(ABREV_TIPO[k])
        elif k in ABREV:
            saida.append(ABREV[k])
        else:
            saida.append(t)
    return " ".join(saida)


def _razao(a, b):
    return SequenceMatcher(None, a, b, autojunk=False).ratio() * 100


def similaridade(digitado, candidato):
    """0 a 100: o quanto o bairro digitado (talvez incompleto) lembra o do mapa."""
    a, c = norm(expandir(digitado)), norm(expandir(candidato))
    if not a or not c:
        return 0
    if a == c:
        return 100
    curto, longo = (a, c) if len(a) <= len(c) else (c, a)
    melhor = _razao(a, c)
    n = len(curto)
    for i in range(len(longo) - n + 1):
        melhor = max(melhor, _razao(curto, longo[i:i + n]))
    # todas as palavras digitadas são o começo de alguma palavra do candidato
    ta = [t for t in a.split() if t not in STOP]
    tc = c.split()
    if ta and all(any(w.startswith(t) for w in tc) for t in ta):
        melhor = max(melhor, 92)
    return round(melhor)


def nominatim(q):
    """Máximo de 1 requisição por segundo + cache em disco."""
    global _ultimo
    chave = "nom:" + q
    if chave in _cache:
        return _cache[chave]
    with _nom_lock:
        if chave in _cache:  # outra thread pode ter buscado enquanto esperávamos
            return _cache[chave]
        espera = PAUSA_NOMINATIM - (time.time() - _ultimo)
        if espera > 0:
            time.sleep(espera)
        try:
            r = requests.get(
                "https://nominatim.openstreetmap.org/search", timeout=15,
                headers={"User-Agent": UA},
                params={"q": q, "format": "jsonv2", "addressdetails": 1, "limit": 10,
                        "countrycodes": "br", "viewbox": VIEWBOX, "bounded": 1,
                        "accept-language": "pt-BR", "dedupe": 1})
        finally:
            _ultimo = time.time()
        if r.status_code == 429:
            raise RuntimeError("O Nominatim pediu para diminuir o ritmo (erro 429). "
                               "Aguarde alguns minutos e tente de novo.")
        r.raise_for_status()
        _cache[chave] = r.json()
    _salvar()
    return _cache[chave]


def viacep(cep):
    """Só é chamada quando o usuário escreve um CEP na linha."""
    chave = "cep:" + cep
    if chave in _cache:
        return _cache[chave]
    r = requests.get("https://viacep.com.br/ws/{}/json/".format(cep), timeout=8)
    dado = r.json() if r.ok else {"erro": True}
    if r.ok:
        _cache[chave] = dado
        _salvar()
    return dado


def extrair_cep(linha):
    m = RE_CEP.search(linha)
    if not m:
        return None, linha
    return m.group(1) + m.group(2), linha[:m.start()] + " " + linha[m.end():]


def separar(texto):
    """Divide 'rua, bairro' (aceita vírgula, ponto e vírgula, tab ou ' - ')."""
    partes = [p.strip(" -") for p in RE_SEPARADOR.split(texto.strip())]
    partes = [p for p in partes
              if p and not norm(p).startswith("rondonopolis") and norm(p) not in IGNORAR_PARTE]
    if not partes:
        return "", ""
    if len(partes) == 1:
        return partes[0], ""
    if RE_NUMERO.match(norm(partes[-1])):  # termina em número: não há bairro
        return ", ".join(partes), ""
    return ", ".join(partes[:-1]), partes[-1]


def juntar(*notas):
    return " ".join(n for n in notas if n) or None


def candidatos_nominatim(rua, bairro):
    dados = nominatim("{}, {}, {}".format(expandir(rua, tipo=True), CIDADE, UF))
    alvo = bairro
    cands, vistos = [], set()
    for p in dados:
        a = p.get("address", {})
        if p.get("category") == "boundary" or p.get("addresstype") in TIPOS_AMPLOS:
            continue
        if norm(CIDADE) not in norm(p.get("display_name", "")):
            continue
        road = a.get("road") or p.get("name") or p["display_name"].split(", ")[0]
        bairros = [a[k] for k in CHAVES_BAIRRO if a.get(k)]
        b = bairros[0] if bairros else ""
        hn = a.get("house_number", "")
        chave = (norm(road), norm(b), hn)
        if chave in vistos:
            continue
        vistos.add(chave)
        score = max((similaridade(alvo, x) for x in bairros), default=0) if alvo else 0
        endereco = ", ".join(x for x in (
            "{}, {}".format(road, hn) if hn else road, b, "{} - {}".format(CIDADE, UF)) if x)
        cands.append({"endereco": endereco, "lat": float(p["lat"]), "lng": float(p["lon"]),
                      "bairro": b, "rua": road, "score": score})
    # sorted é estável: sem bairro digitado, mantém a ordem de relevância do Nominatim
    cands = sorted(cands, key=lambda x: x["score"], reverse=True)[:6]
    for c in cands:
        repetido = sum(1 for o in cands if o["bairro"] == c["bairro"]) > 1
        c["rotulo"] = (c["bairro"] or "sem bairro") + (" ({})".format(c["rua"]) if repetido else "")
    return cands


def resolver(linha):
    cep, resto = extrair_cep(linha)
    rua, bairro = separar(resto)
    nota = None

    if cep:
        fmt = "{}-{}".format(cep[:5], cep[5:])
        if cep.endswith("000"):  # CEP genérico da cidade: não identifica rua, nem consulta a ViaCEP
            nota = "CEP {} é genérico da cidade e foi ignorado.".format(fmt)
        else:
            try:
                info = viacep(cep)
            except Exception:
                nota = "ViaCEP indisponível; busca feita só com o texto digitado."
            else:
                if info.get("erro"):
                    nota = "CEP {} não encontrado na ViaCEP.".format(fmt)
                elif norm(info.get("localidade")) != norm(CIDADE):
                    nota = "CEP {} é de {}, não de {}; ignorado.".format(
                        fmt, info.get("localidade"), CIDADE)
                elif not info.get("logradouro"):
                    nota = "CEP {} não identifica uma rua; ignorado.".format(fmt)
                else:
                    logradouro = info["logradouro"].split(" - ")[0].strip()
                    rua = rua or logradouro
                    bairro = info.get("bairro") or bairro
                    nota = "CEP {}: {}, {}".format(fmt, logradouro, info.get("bairro", ""))

    base = {"rua": rua or linha, "bairro": bairro, "nota": nota, "candidatos": []}
    if not rua:
        return {**base, "erro": "Informe o nome da rua. O CEP sozinho não bastou para achá-la."}

    try:
        cands = candidatos_nominatim(rua, bairro)
        if not cands and RE_NUMERO_FINAL.search(rua):
            # número de porta ausente no OpenStreetMap: tenta só a rua
            sem_numero = RE_NUMERO_FINAL.sub("", rua)
            cands = candidatos_nominatim(sem_numero, bairro)
            if cands:
                nota = juntar(nota, "Número não encontrado no OpenStreetMap; o pino mostra a rua.")
    except requests.exceptions.RequestException as e:
        return {**base, "erro": "Falha ao consultar o Nominatim: {}".format(e)}
    except Exception as e:
        return {**base, "erro": str(e)}
    return {**base, "nota": nota, "candidatos": cands, "erro": None}


@app.get("/")
def index():
    return render_template("index.html", cidade=CIDADE, uf=UF)


@app.post("/api/buscar")
def buscar():
    linha = ((request.get_json(silent=True) or {}).get("linha") or "").strip()
    if not linha:
        return jsonify({"erro": "Linha vazia."}), 400
    return jsonify(resolver(linha))


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
