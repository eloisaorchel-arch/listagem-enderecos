# Localizador de endereços (Rondonópolis - MT)

Cole vários endereços de uma vez (um por linha) e o site mostra cada um no mapa, em sequência.
A busca é sempre restrita a **Rondonópolis - MT, Brasil**, mesmo quando o bairro está escrito de forma incompleta.

Versão **100% gratuita, sem chaves de API e sem cartão de crédito**:

| Função | Serviço |
|---|---|
| Achar as coordenadas | **Nominatim** (OpenStreetMap) |
| Exibir o mapa | **Leaflet** com mapa do OpenStreetMap |
| Completar rua e bairro a partir de um CEP | **ViaCEP**, só quando a linha contém um CEP |

## Como rodar

1. Instale o Python 3.9 ou mais novo.
2. Na pasta do projeto, instale as dependências:
   ```
   python -m venv .venv
   .venv\Scripts\activate        # Windows  (Linux/Mac: source .venv/bin/activate)
   pip install -r requirements.txt
   ```
3. Copie `.env.example` para `.env` e troque `CONTATO_EMAIL` pelo seu e-mail
   (a política do Nominatim exige identificar quem está consultando).
4. Rode `python app.py` e abra http://localhost:5000

## Como usar

Uma linha por endereço, no formato `rua, bairro` (o número da porta é opcional):

```
Rua das Flores, 120, Jd Atlantico
Av. Exemplo, Vl Aurora
Rua Exemplo, Centro, 78700-000
```

- Abreviações comuns (Jd, Vl, Pq, Res, Cj, Av, R...) são expandidas automaticamente.
- O bairro digitado serve para **ordenar** os resultados: a opção mais parecida vem marcada.
  Se a rua existir em mais de um bairro, aparecem botões com os bairros alternativos; clique para trocar o pino.
- Use **‹ ›** (ou as setas do teclado) para ir de endereço em endereço, **Percorrer** para avançar sozinho
  a cada 4 segundos e **Ver todos** para enquadrar todos os pinos.
- Cada endereço tem links para abrir no Google Maps ou no OpenStreetMap.
- **Parar busca** interrompe a consulta no meio; o que já foi achado continua no mapa.

## Como o CEP é tratado

- A ViaCEP **só é consultada quando a linha tem um CEP**. Sem CEP, ela nunca é chamada.
- CEPs terminados em `000` (genéricos da cidade, como 78700-000) são ignorados sem nem consultar a ViaCEP:
  a linha é buscada só pelo que você digitou, e uma nota avisa isso.
- CEP de outra cidade, inexistente ou que não identifica rua também é ignorado, com nota explicando.
- Se o CEP é específico, a rua (quando você não digitou uma) e o bairro completo vêm da ViaCEP.
- Linha só com CEP e sem rua não é buscada: o CEP sozinho não tem coordenadas.

## Regras de uso e limites

- O servidor público do Nominatim aceita **1 requisição por segundo**. O programa já espera esse intervalo,
  então 60 endereços levam cerca de 1 minuto. Cada resposta fica salva em `cache.json`:
  repetir um endereço é instantâneo. Apague o arquivo se quiser refazer buscas antigas.
- Use para consultas pontuais. Rodar milhares de endereços seria abusar do serviço gratuito;
  para isso, hospede o seu próprio Nominatim.
- Mantenha a atribuição "OpenStreetMap" visível no mapa (já vem pronta).
- Se o Nominatim responder erro 429, espere alguns minutos.
- Número da porta: se ele não existir no OpenStreetMap, o programa tenta de novo só com a rua e avisa na nota.

## Qualidade dos dados

Os dados do OpenStreetMap dependem do que os voluntários mapearam em cada região.
Em Rondonópolis podem faltar números de portas, bairros ou ruas menores, e o Google costuma ser mais completo no Brasil.
Teste com 10 a 15 endereços reais seus antes de depender do resultado. Itens sem bairro aparecem como "sem bairro".

## Estrutura

```
app.py                 back end Flask (Nominatim, ViaCEP, cache, ordenação por bairro)
templates/index.html   página (Leaflet, lista, navegação, efeitos)
requirements.txt       flask, requests, python-dotenv
.env.example           modelo do arquivo .env
```
