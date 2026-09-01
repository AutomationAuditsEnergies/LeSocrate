# Évaluation RAG Azure

Ce dossier contient un banc d'évaluation simple pour comparer plusieurs modes de recherche Azure OpenAI On Your Data, notamment:

- `simple` : recherche textuelle classique, côté Azure AI Search.
- `vector_simple_hybrid` : recherche hybride texte + vecteur, fusionnée par Azure.

## Lancer l'évaluation

Depuis la racine du repo:

```bash
python3 tools/rag/evaluate_rag.py \
  --dataset tools/rag/eval_questions.example.jsonl \
  --query-types simple,vector_simple_hybrid \
  --output-dir rag_eval_runs
```

Le script charge `backend/.env` si le fichier existe. Les variables attendues sont:

- `AZURE_OPENAI_ENDPOINT`
- `AZURE_OPENAI_API_KEY`
- `AZURE_OPENAI_DEPLOYMENT`
- `AZURE_SEARCH_ENDPOINT`
- `AZURE_SEARCH_API_KEY`
- `AZURE_SEARCH_INDEX_NAME`
- `AZURE_OPENAI_EMBEDDING_DEPLOYMENT` pour les modes vectoriels

## Dataset

Le fichier JSONL contient une question par ligne:

```json
{"id":"q001","question":"...","expected_terms":["terme attendu"],"out_of_scope":false}
```

Champs:

- `id` : identifiant stable de la question.
- `question` : question posée au RAG.
- `expected_terms` : termes ou expressions attendus dans la réponse. Sert à calculer un rappel lexical simple.
- `out_of_scope` : `true` si la bonne réponse doit être un refus du type "ce n'est pas dans les documents".

Pour un résultat défendable dans un mémoire, utiliser au moins:

- 20 à 30 questions dont la réponse est dans le corpus.
- 5 à 10 questions hors corpus pour tester l'anti-hallucination.
- Des questions lexicales exactes et des questions reformulées.

## Métriques produites

Le rapport JSON/CSV contient:

- `expected_term_recall` : proportion des termes attendus retrouvés dans la réponse.
- `citation_expected_term_recall` : proportion des termes attendus retrouvés dans les citations/chunks remontés par Azure. C'est la métrique la plus proche d'une évaluation du retrieval.
- `mrr_proxy` : approximation du MRR à partir du rang de la première citation contenant un terme attendu.
- `out_of_scope_refusal_rate` : taux de refus correct sur les questions hors corpus.
- `citation_count` : nombre de citations/documents remontés par Azure.
- `latency_ms` : latence de l'appel.

Ces métriques ne remplacent pas une annotation humaine, mais elles suffisent pour comparer rapidement `simple` et `vector_simple_hybrid` sur le même corpus.

## Protocole conseillé pour le mémoire

Ne pas baser le résultat principal uniquement sur un PDF artificiel. Le mieux est:

1. Évaluer d'abord sur le vrai corpus de cours indexé dans Azure.
2. Ajouter éventuellement un petit corpus artificiel contrôlé pour illustrer les cas où la recherche hybride aide particulièrement: acronymes, codes rares, termes métier exacts, formulations proches mais non identiques.
3. Présenter les résultats principaux sur le corpus réel, puis utiliser le corpus artificiel comme étude de cas explicative.
