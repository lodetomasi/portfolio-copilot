# Prompt da incollare in Claude Code

Usa questo come primo prompt:

```text
Sei il lead engineer del progetto Portfolio Copilot.

1. Leggi per intero:
   - CLAUDE.md
   - docs/PRD.md
   - docs/ARCHITECTURE.md
   - docs/FINANCIAL_LOGIC.md
   - docs/IMPLEMENTATION_PLAN.md

2. Ispeziona il repository e l'SDK MCP effettivamente installato.
3. Esegui:
   - uv sync
   - uv run pytest
   - uv run ruff check .
4. Correggi qualsiasi incompatibilità dello scaffold con MCP Python SDK v2.
5. Implementa la V1 in piccoli step testabili.
6. Non aggiungere API a pagamento.
7. Non implementare accesso diretto al broker o trading automatico.
8. Tutti i calcoli finanziari devono essere deterministici in Python.
9. Ogni dato esterno deve avere source/as_of/confidence.
10. Se una metrica non è disponibile, non inventarla.

Al termine fammi:
A. riepilogo di ciò che è funzionante;
B. test eseguiti;
C. eventuali limiti del provider gratuito;
D. il comando esatto per registrare l'MCP in Claude Code;
E. 5 prompt di prova end-to-end.
```

## Prompt quando hai un export del broker vero

```text
Ti allego un export del broker reale.
Usalo solo per capire il formato.
Non committare dati personali o valori reali.
Crea una fixture sintetica equivalente, aggiorna il parser e aggiungi test.
```

## Prompt per migliorare stock picker

```text
Rendi lo stock picker portfolio-aware.
Un titolo con score alto non deve diventare BUY se viola limiti di settore,
single-name, speculative bucket, leveraged bucket o cost efficiency.
Aggiungi reason codes e test.
```
