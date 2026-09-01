# Brouillon — Introduction générale et partie pipeline

> Brouillon de rédaction. Le texte ci-dessous vise un style mémoire : plus narratif que
> l'audit technique, mais avec une logique d'ingénierie claire.

## Introduction générale — version de travail

Audits Énergies est une jeune entreprise positionnée à la fois sur le marché du courtage
en énergie et sur celui de la formation professionnelle. Son activité historique consiste
à accompagner des entreprises dans la renégociation de leurs contrats d'énergie, dans un
contexte où l'ouverture du marché à la concurrence a rendu les offres plus nombreuses,
plus complexes et plus difficiles à comparer. Progressivement, l'entreprise a également
développé une activité de formation, d'abord pour répondre à ses propres besoins de
recrutement et de montée en compétence, puis pour proposer des parcours de formation
plus structurés à distance.

Cette double activité a fait apparaître une même difficulté : comment continuer à se
développer avec une équipe réduite, tout en conservant un niveau de qualité suffisant ?
Dans une petite structure, certaines tâches prennent rapidement une place importante :
préparer des supports, produire des contenus pédagogiques, déposer des fichiers sur la
plateforme, suivre les présences, répondre aux questions des apprenants, ou encore
adapter les contenus d'une formation à l'autre. Ces tâches sont nécessaires, mais elles
mobilisent du temps humain sur des opérations répétitives, alors que ce temps pourrait
être consacré à des missions à plus forte valeur ajoutée.

La formation à distance illustre particulièrement bien ce problème. Dans le fonctionnement
initial, les contenus pédagogiques devaient être préparés à l'écrit, relus, transformés en
audio, puis déposés manuellement sur la plateforme. Ce mode de fonctionnement pouvait
convenir à petite échelle, mais il devenait difficile à généraliser : chaque nouvelle
formation demandait un investissement humain important, la qualité dépendait fortement
des disponibilités des intervenants, et la moindre modification impliquait de reprendre
plusieurs étapes de production. Plus largement, la plateforme permettait de diffuser un
cours, mais elle n'était pas encore capable de produire, organiser, enrichir et contrôler
elle-même l'ensemble d'un parcours pédagogique.

L'arrivée des modèles de langage et des outils de synthèse vocale a donc ouvert une piste
évidente : automatiser une partie de cette chaîne. Pourtant, l'objectif ne pouvait pas se
limiter à "mettre de l'IA" dans la plateforme. Un cours de formation n'est pas un simple
texte généré. Il doit respecter un programme, être compréhensible à l'oral, tenir dans une
durée donnée, éviter les approximations, rester conforme à un cadre pédagogique et
éthique, puis être accompagné de supports visuels et d'exercices. De la même manière,
un assistant conversationnel pédagogique ne peut pas répondre comme un chatbot
généraliste : il doit s'appuyer sur les documents de formation, citer les bonnes sources et
éviter d'inventer des informations.

La problématique de ce mémoire peut donc être formulée ainsi :

**Comment concevoir une plateforme de formation autonome alimentée par l'intelligence
artificielle, capable de produire, diffuser et accompagner des contenus pédagogiques, tout
en garantissant leur qualité, leur traçabilité et leur pertinence pour les apprenants ?**

Cette problématique suppose de traiter plusieurs questions d'ingénierie. La première
concerne la production des contenus : comment passer d'un programme officiel ou d'un
référentiel métier à des journées de formation complètes, structurées et exploitables en
audio ? La deuxième concerne la qualité : comment contrôler un contenu généré par IA
avant qu'il ne soit diffusé à des élèves ? La troisième concerne l'accompagnement : comment
permettre aux apprenants de poser des questions et d'obtenir des réponses contextualisées,
sans exposer la plateforme aux limites d'un modèle de langage généraliste ? Enfin, la
dernière concerne l'évaluation : comment mesurer ce que l'automatisation apporte
réellement, au-delà du simple fait que le système fonctionne techniquement ?

Mon travail s'inscrit dans cette tension entre automatisation et contrôle. L'enjeu n'a pas
été seulement de remplacer une tâche humaine par un appel à une API, mais de concevoir
une chaîne de production suffisamment fiable pour être utilisée dans un contexte de
formation. Cela m'a conduit à comparer plusieurs approches, à abandonner certaines
solutions trop fragiles, puis à faire évoluer progressivement l'architecture vers une
pipeline plus structurée, plus auditable et plus mesurable.

## Partie pipeline — De la génération audio à une chaîne de production pédagogique

### 1. État de l'art et premiers arbitrages autour de la voix

La première question posée par l'automatisation des cours était très concrète : comment
produire plusieurs heures d'audio de formation sans dépendre à chaque fois d'un
intervenant humain ? Une solution simple aurait été de conserver le fonctionnement
historique, c'est-à-dire faire préparer puis enregistrer les cours par une personne. Cette
approche garde évidemment des qualités : la voix humaine est naturelle, les intentions
pédagogiques peuvent être adaptées en direct, et les hésitations ou reformulations font
partie d'un style d'enseignement vivant. En revanche, elle devient coûteuse et difficile à
industrialiser dès qu'il faut produire plusieurs modules, mettre à jour des contenus ou
adapter une formation à un nouveau titre professionnel.

L'autre extrême consistait à utiliser une synthèse vocale basique. Des solutions comme
gTTS ou certaines voix standards permettent de générer rapidement de l'audio à faible
coût. Elles sont utiles pour prototyper, mais elles posent vite une limite pour de la
formation longue : la voix peut sembler trop mécanique, le rythme est parfois difficile à
contrôler, et l'expérience d'écoute devient moins agréable sur plusieurs heures. Pour une
plateforme de formation, la qualité perçue de la voix compte presque autant que le
contenu, car l'élève passe une grande partie de son temps à écouter.

Il fallait donc comparer des solutions de voix plus avancées. ElevenLabs faisait partie des
options évidentes, notamment pour la qualité sonore et le naturel des voix. Mais son coût
devient rapidement un sujet dès qu'on raisonne en heures de formation et non en courtes
démonstrations. Dans notre cas, il ne s'agissait pas de générer quelques minutes d'audio,
mais des journées complètes, potentiellement réutilisées pour plusieurs promotions. Le
rapport qualité-prix devenait donc un critère central.

Fish Audio est apparu comme un compromis intéressant. La qualité était suffisante pour
produire des cours longs, le coût semblait plus compatible avec une production régulière,
et l'API permettait d'intégrer la génération audio dans une chaîne automatisée. Ce choix
n'était pas seulement un choix technique de fournisseur. Il changeait la manière de
penser le projet : si le coût de production audio devenait inférieur au coût d'une production
humaine répétée, alors il devenait pertinent de se demander si toute la chaîne de création
du cours pouvait être automatisée.

Cette réflexion a déplacé le problème. Au départ, la question semblait être : "Quelle voix
utiliser pour lire un cours ?" En pratique, la vraie question est devenue : "Comment
produire un texte de cours suffisamment bon pour être lu automatiquement ?" Une bonne
voix ne compense pas un mauvais script. Si le texte est trop long, répétitif, mal structuré,
ou s'il contient des formulations qui ne passent pas à l'oral, l'audio final sera mauvais,
même avec un bon moteur TTS. La qualité de la voix n'est donc qu'un maillon de la chaîne.
Le vrai sujet d'ingénierie se situe dans la production et le contrôle du contenu en amont.

### 2. Contexte initial : automatiser la production des cours audio

L'objectif de départ était de générer des journées de formation complètes, capables d'être
transformées en fichiers audio puis intégrées à la plateforme. Cette contrainte est plus
complexe qu'elle n'en a l'air. Un cours écrit pour être lu à l'écran n'est pas forcément un
bon cours à écouter. Il faut un style oral, des transitions, des rappels, des exemples, des
pauses naturelles, et un rythme suffisamment clair pour que l'apprenant puisse suivre
sans support permanent.

À cela s'ajoutait une contrainte de durée. Les fichiers audio devaient correspondre à des
blocs précis de la journée de formation. Un texte trop court créait du vide ou donnait un
sentiment de contenu insuffisant. Un texte trop long risquait au contraire de dépasser le
temps disponible, de provoquer une coupure ou de désynchroniser la journée. La génération
ne pouvait donc pas se contenter de produire "un bon texte" ; elle devait produire un texte
adapté à une fenêtre audio.

Enfin, le contenu devait rester conforme au programme et au cadre pédagogique. Le modèle
ne devait pas inventer des informations, promettre des choses qui ne sont pas dans le
référentiel, ni faire apparaître dans le discours oral des contraintes internes comme les
budgets de mots, les blocs audio ou les horaires techniques. L'apprenant doit entendre un
formateur clair et naturel, pas les traces de la machine qui a produit le cours.

### 3. Première approche : générer directement les cours

La première intuition a été de s'appuyer fortement sur le modèle de langage. Si un LLM
est capable de rédiger un texte pédagogique, il semblait naturel de lui fournir le contenu
du module, les règles de style, les contraintes éthiques, les consignes de synthèse vocale
et le budget de mots, puis de lui demander de générer le cours.

Cette approche a progressivement été structurée autour de créneaux audio. Une journée
était découpée en plusieurs moments, chacun avec une intention pédagogique : démarrer
la journée, introduire un thème, développer une partie, approfondir avec des exemples,
puis conclure. Pour améliorer la qualité, la génération se faisait en plusieurs passes :
une première pour poser les bases, une deuxième pour rendre le contenu plus pratique,
et une troisième pour enrichir ou finaliser le discours.

Cette solution avait plusieurs avantages. Elle permettait de produire rapidement des
contenus longs, elle donnait une première forme à la journée, et elle rendait possible une
automatisation bien plus rapide qu'un enregistrement humain. Elle a aussi permis de
valider une hypothèse importante : l'IA pouvait effectivement contribuer à produire des
cours audio exploitables, à condition d'être fortement guidée.

Mais cette première approche avait une faiblesse : elle faisait porter trop de responsabilités
au prompt. Le même ensemble de consignes devait gérer la structure pédagogique, le style
oral, la conformité, la durée, les transitions, les exemples, les règles de synthèse vocale et
les interdictions. Plus le prompt devenait complet, plus il devenait difficile à maintenir.
Une règle ajoutée pour corriger un problème pouvait en créer un autre ailleurs. Et quand
un défaut apparaissait dans le résultat final, il était difficile de savoir s'il venait du plan,
du style, du budget, d'une transition ou d'une correction tardive.

### 4. Limites observées

La première limite concernait la cohérence pédagogique. Sur des contenus courts, le
modèle arrive généralement à garder un fil clair. Sur plusieurs heures de formation, c'est
plus difficile. Certaines introductions se répétaient, des transitions semblaient artificielles,
et il arrivait qu'une partie donne l'impression de finir le sujet précédent plutôt que
d'ouvrir un nouveau thème. Le problème n'était pas seulement stylistique : il révélait que
la structure de la journée n'était pas assez explicitement contrôlée.

La deuxième limite venait du rapport entre texte et audio. Le texte était généré selon des
créneaux, puis retravaillé pour entrer dans des blocs audio. Or une frontière technique ne
correspond pas toujours à une frontière pédagogique. Un passage pouvait être coupé au
mauvais endroit, une conclusion pouvait arriver trop tôt ou trop tard, et les ajustements
de longueur pouvaient modifier un texte qui avait déjà été relu ou corrigé. Cela montrait
qu'il ne suffisait pas de contrôler la longueur à la fin : il fallait intégrer la contrainte de
durée dès la conception du contenu.

La troisième limite concernait la conformité et la qualité. Les premières reviews étaient
trop globales. Elles cherchaient à corriger à la fois le style oral, les formulations sensibles,
les éventuelles hallucinations et parfois la structure. En pratique, cela rendait le système
difficile à piloter. Une correction destinée à humaniser le texte pouvait modifier une
formulation importante. Une correction de conformité pouvait allonger le texte. Et comme
les reviews intervenaient tard dans la chaîne, certains problèmes n'étaient visibles qu'après
une grande partie du travail déjà effectuée.

La quatrième limite était le manque de traçabilité. Lorsque la sortie principale est un
fichier texte final, il est difficile de comprendre l'histoire du contenu. On peut lire le texte,
mais on ne sait pas toujours quel plan l'a produit, quelle règle a été appliquée, quelle
section a été modifiée, ni pourquoi une formulation a changé. Pour un prototype, ce n'est
pas forcément bloquant. Pour une plateforme de formation qui doit produire des contenus
réutilisables, c'est un problème majeur. Il faut pouvoir expliquer, corriger et auditer.

Enfin, la génération des supports visuels posait une question similaire. Si les slides sont
créées après coup en analysant le texte final, elles risquent de résumer ce qui est le plus
visible dans le texte, sans forcément correspondre aux moments pédagogiques les plus
importants. Or une bonne slide ne doit pas seulement illustrer une phrase ; elle doit
accompagner une intention pédagogique.

### 5. Choix de refonte : rendre la pipeline contrôlable

Ces limites ont conduit à une refonte de la logique de génération. L'idée centrale a été de
ne plus considérer le texte final comme le premier objet important, mais de créer d'abord
un contrat pédagogique. Ce contrat prend la forme d'un plan structuré : il décrit les cours
de la journée, leurs parties, leurs objectifs, leurs budgets, leurs moments importants et
les points qui pourront être visualisés sous forme de slides.

Ce choix change profondément la pipeline. Le modèle ne part plus directement dans une
longue rédaction. Il commence par organiser la journée. Ensuite seulement, chaque section
est générée dans un périmètre limité. Cela permet de mieux contrôler ce que le modèle
doit dire, ce qu'il ne doit pas dire, et comment chaque partie s'inscrit dans l'ensemble.

La génération par section répond à un problème très concret : réduire la charge cognitive
imposée au modèle. Au lieu de lui demander de produire plusieurs heures de formation
en gardant toutes les contraintes en tête, on lui demande de traiter une partie précise,
avec un objectif clair, un budget propre et un contexte limité. C'est une approche plus
proche d'une chaîne de production industrielle : chaque étape a une responsabilité définie.

Les prompts ont également été séparés. Au lieu d'un gros fichier portant toutes les règles,
la pipeline distingue le style général du cours, la création du plan, la génération d'une
section, la réécriture liée au budget, l'humanisation orale et la conformité. Cette
modularisation rend le système plus maintenable : lorsqu'un problème concerne le style,
on peut intervenir sur le prompt de style ; lorsqu'il concerne le respect du plan, on agit
sur l'audit d'adhérence ; lorsqu'il concerne la conformité, on agit sur les règles dédiées.

La qualité est ensuite contrôlée par plusieurs reviews ciblées. L'objectif n'est pas de
multiplier les validations pour complexifier le système, mais de séparer les natures de
problèmes. Une review vérifie que le texte respecte le plan. Une autre ajuste le volume.
Une autre traite les formulations sensibles. Une autre améliore l'oralité sans restructurer
le contenu. Enfin, une conformité finale vérifie les règles les plus importantes. Cette
séparation évite qu'une seule passe essaie de tout corriger en même temps.

Enfin, la pipeline conserve des artefacts intermédiaires. Le plan, les sections générées,
les corrections, les versions avant/après, le plan audio et les éléments liés aux slides sont
persistés. Cette décision peut sembler technique, mais elle est importante sur le plan
méthodologique : elle transforme la génération IA en processus observable. Si une erreur
apparaît, on peut remonter à l'étape qui l'a introduite. Si une correction est appliquée, on
peut la justifier. Si un support visuel est généré, on peut le rattacher à une intention du
plan et à un passage source.

### 6. Apport de la nouvelle architecture

Le principal apport de cette nouvelle architecture est la maîtrise. La première pipeline
cherchait surtout à produire un résultat final. La nouvelle cherche à contrôler le chemin
qui mène à ce résultat. Cette différence est essentielle dans un projet d'ingénierie : un
système automatisé ne doit pas seulement fonctionner quand tout se passe bien, il doit
aussi permettre de comprendre ses erreurs.

Le plan structuré améliore la cohérence pédagogique. Les introductions, les transitions
et les conclusions ne sont plus seulement des formulations ajoutées au fil de la génération :
elles s'inscrivent dans une progression prévue. Les ouvertures peuvent être rédigées après
le contenu principal, en tenant compte de ce qui a réellement été produit. Cela limite les
répétitions et donne une meilleure continuité à la journée.

La gestion du budget devient également plus claire. Au lieu de demander au modèle de
"faire à peu près la bonne longueur", la pipeline impose des budgets côté serveur et vérifie
leur cohérence. Il reste nécessaire de mesurer en production la précision réelle entre
nombre de mots et durée audio, mais le système ne repose plus uniquement sur
l'auto-discipline du modèle.

Les slides bénéficient aussi de cette approche. Plutôt que d'être seulement extraites du
texte final, elles sont prévues dès le plan à partir de moments pédagogiques identifiés.
Cela permet de produire des supports plus cohérents avec le cours, et surtout plus
traçables : une slide peut être reliée à un passage source et à une intention pédagogique.

Enfin, l'auditabilité rend la plateforme plus crédible. Dans un contexte de formation, il ne
suffit pas de dire qu'un contenu a été généré. Il faut pouvoir montrer comment il a été
construit, quelles règles ont été vérifiées, et quelles corrections ont été apportées. Cette
logique est également utile pour expliquer le travail à un manager ou à un jury : la valeur
du projet ne réside pas seulement dans l'automatisation, mais dans la capacité à encadrer
cette automatisation.

### 7. Limites et métriques à mesurer

Il est important de distinguer les paramètres de la pipeline et les résultats mesurés. Par
exemple, le nombre de cours par journée, le nombre de workers parallèles, les ratios de
budget ou la vitesse moyenne utilisée pour estimer la durée audio sont des paramètres de
conception. Ils montrent que le système a été pensé, mais ils ne prouvent pas à eux seuls
que la solution est meilleure. Pour démontrer l'apport de la pipeline, il faut définir des
métriques d'évaluation.

Plusieurs métriques peuvent être utilisées pour mesurer l'amélioration. Sur la production,
on peut comparer le temps nécessaire pour créer une formation avant et après
automatisation, le nombre d'interventions humaines restantes, le coût de production par
module, ou encore le nombre d'erreurs bloquantes détectées avant la génération audio.
Sur la qualité pédagogique, on peut mesurer le nombre de répétitions détectées, le respect
du plan, le taux de sections corrigées par les reviews, ou la cohérence entre les slides et
les passages sources. Sur l'audio, il faut mesurer l'écart entre durée cible et durée réelle,
le nombre de blocs trop courts ou trop longs, et les éventuelles coupures.

L'évaluation doit aussi intégrer les élèves. La plateforme ne peut pas être jugée uniquement
sur des critères techniques. Il faut mesurer la satisfaction des apprenants, leur taux de
complétion, leurs résultats aux QCM, le nombre de questions posées à l'assistant, ou
encore leur perception de la clarté des cours. Ces métriques permettront de répondre à la
question centrale : l'automatisation a-t-elle seulement réduit le coût de production, ou
a-t-elle aussi amélioré l'expérience de formation ?

Enfin, certaines limites doivent être reconnues. La pipeline reste pensée autour d'une
structure de journée relativement fixe. La conversion entre nombre de mots et durée audio
reste une approximation à valider empiriquement. Le coût exact des appels IA doit être
mesuré sur des générations réelles. Et même si Fish Audio rend l'automatisation
économiquement plus crédible, il faudra comparer le coût complet de la chaîne, incluant la
génération de texte, les reviews, les slides et les éventuelles relances.

Ces limites ne remettent pas en cause l'intérêt de l'approche. Elles montrent au contraire
la logique du projet : passer d'une automatisation opportuniste à une automatisation
contrôlée, puis rendre cette automatisation mesurable. C'est cette progression qui constitue
le cœur de la démarche d'ingénierie menée sur la pipeline de contenu.

