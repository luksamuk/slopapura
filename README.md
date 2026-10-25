# SlopApura

**slop + apuração.** Um dashboard pra acompanhar a totalização oficial do TSE
(eleições federais/estaduais de 2026) em tempo real, direto dos JSONs de divulgação
oficial — sem chave de API, sem cadastro, sem depender do site do TSE aguentar o
tráfego de hoje.

## Disclaimer descarado (o que você já imaginou)

Este projeto foi **100% vibecodado**. Não tem test suite, não tem CI, não tem
arquitetura "séria" — tem um FastAPI e uma página HTML que funcionam, escritos
na manhã da apuração. Se quiser julgar por isso, fique à vontade: é deliberado.
O que ele faz, ele faz honestamente:

- Consulta os JSONs oficiais de divulgação do TSE (`resultados.tse.jus.br/oficial/`)
- Cacha localmente (TTL de 270s + conditional request; hit de 304 em ~9ms quente)
- Nunca marreta o origin em pré-apuração (404 também é cacheado, 30s)
- Projeção local **conservadora e não oficial** de eleito (só impossibilidade matemática)

## Subir

    ./run.sh

- UI: http://localhost:8892
- API: http://localhost:8891 (docs em /docs)

Requisito: Python 3.12+. Docker é opcional (`backend/Dockerfile`);
`up.sh` sobe de novo sem rebuild, `down.sh` mata tudo.

## Endpoints

| Rota | O que faz |
|---|---|
| `GET /api/health` | liveness |
| `GET /api/config` | config canônico do TSE (códigos de eleição do ciclo) |
| `GET /api/resultados?uf=mg&cargo=3&turno=2` | um cargo numa UF (1=Pres 3=Gov 5=Sen 6=DepFed 7=DepEst 8=DepDist) |
| `GET /api/painel?ufs=br,mg&turno=2` | snapshot agregado pro dashboard |
| `GET /api/demo` | fixture real do 2º turno de 2022 (teste de render pré-17h) |
| `GET /api/painel?mock=true` | 5 cards clonados, só validar layout |

## Fonte e etiqueta

`resultados.tse.jus.br/oficial/ele2026/<código>/dados/<uf>/<uf>-c<cargo>-e<código>-u.json`.
Códigos 2026 (do config canônico): federal 1ºT **6257** / 2ºT **6258**;
estadual 1ºT **6259** / 2ºT **6260**. O feed é stream: o TSE reescreve o mesmo
arquivo a cada lote totalizado (1-5 min no pico). Cadência própria: ~5 URLs a cada
270s = fração ínfima do limite medido por IP. Sejais gentil. `www.tse.jus.br`
bloqueia curl; os dados abertos (`dadosabertos.tse.jus.br`) não.

## Limitações honestas

- Deputados são proporcionais: o top-N por votos nominais NÃO é a eleição
  (quociente eleitoral/partidário é fechado pelo TSE só no fim).
- A projeção "eleito (proj.)" é nossa, não do TSE — marca só quando a vantagem
  supera o pior caso de eleitores pendentes.
- Em 2º turno, os painéis de UF só mostram cargos em disputa; o resto fechou no 1ºT.
- As fotos dos candidatos vêm de outra rota do TSE que fecha com 403/429 no dia D —
  o fallback de iniciais assume e a foto volta quando a rota reabrir.

## Arquitetura (o "grandioso" plano)

    backend/
      tse_client.py   # fetch + cache condicional + negative-cache de 404
      apuracao.py     # normalização do payload + projeção matemática
      main.py         # rotas FastAPI
      demo_fixture.json
    frontend/
      index.html      # tudo: CSS, JS, grid, tooltips — um arquivo e fim
    serve.py          # um servidor só: estático + proxy /api

Foi escrito pra morrer depois da eleição. Sobreviveu ao 1º turno; agora tá aqui
de novo pro 2º. Se sobreviver a ambos, foi bom demais pra morrer.

## Licença

WTFNMFPL v1 ("Do What The Fuck You Want To But It's Not My Fault") — a evolução da
WTFPL. Faz o que quiser com o slop, e se der problema, problema seu.