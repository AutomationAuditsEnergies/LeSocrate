# EFREI PARIS

**MÉMOIRE DE FIN D'ANNÉE PGE ING3 - 2025-2026**
(302)7356

**Conception d'une plateforme de formation autonome alimentée par l'intelligence artificielle**

* **Auteur :** ISSAD Nassim

* **Promotion :** ING3/M2-BDML

* **Tuteur entreprise :** M. Mehdi ROUSSELLE

* **Tuteur pédagogique :** M. Moulay AHANSAL

* **Entreprise :** RG FORMATIONS

* **Année académique :** 2025-2026

## SOMMAIRE

* [RÉSUMÉ](#résumé)

* [1. INTRODUCTION GÉNÉRALE](#1-introduction-générale)

  * [1.1 CONTEXTE](#11-contexte)

  * [1.2 STRUCTURE DU MÉMOIRE](#12-structure-du-mémoire)

* [2. POSITION DU PROBLÈME](#2-position-du-problème)

  * [2.1 D'UNE ACTIVITÉ DE FORMATION À UN PROBLÈME D'INDUSTRIALISATION](#21-dune-activité-de-formation-à-un-problème-dindustrialisation)

  * [2.2 LES LIMITES DES APPROCHES REPOSANT SUR L'INTERVENTION HUMAINE](#22-les-limites-des-approches-reposant-sur-lintervention-humaine)

  * [2.3 VERS LA VISION D'UN PROFESSEUR IA](#23-vers-la-vision-dun-professeur-ia)

* [3. ÉTAT DE L'ART](#3-état-de-lart)

  * [3.1 LE PROBLÈME A-T-IL DÉJÀ ÉTÉ RÉSOLU?](#31-le-problème-a-t-il-déjà-été-résolu)

  * [3.2 PREMIÈRE FONCTION: PRODUIRE ET DÉLIVRER UN COURS](#32-première-fonction-produire-et-délivrer-un-cours)

  * [3.3 DEUXIÈME FONCTION: RÉPONDRE AUX QUESTIONS DES APPRENANTS](#33-deuxième-fonction-répondre-aux-questions-des-apprenants)

  * [3.4 SYNTHÈSE GÉNÉRALE DE L'ÉTAT DE L'ART](#34-synthèse-générale-de-létat-de-lart)

  * [3.5 TABLEAU RÉCAPITULATIF DES APPROCHES EXISTANTES](#35-tableau-récapitulatif-des-approches-existantes)

* [4. ÉTUDE ORIGINALE](#4-étude-originale)

  * [4.1 PREMIÈRE FONCTION: PRODUIRE ET DÉLIVRER UN COURS](#41-première-fonction-produire-et-délivrer-un-cours)

  * [4.2 SECONDE FONCTION: RÉPONDRE AUX QUESTIONS DES APPRENANTS](#42-seconde-fonction-répondre-aux-questions-des-apprenants)

* [5. DISCUSSION ET CONCLUSION](#5-discussion-et-conclusion)

  * [5.1 LIMITES ET PISTES D'ÉVOLUTION](#51-limites-et-pistes-dévolution)

  * [5.2 APPORTS PROFESSIONNELS ET MONTÉE EN COMPÉTENCES](#52-apports-professionnels-et-montée-en-compétences)

* [BIBLIOGRAPHIE](#bibliographie)

* [REMERCIEMENTS](#remerciements)

## RÉSUMÉ

Ce mémoire présente la conception d'une plateforme de formation autonome alimentée par l'intelligence artificielle, développée dans le contexte de l'entreprise Audits Énergies et de son activité de formation Sales Hacking. Initialement spécialisée dans le courtage en énergie, l'entreprise a progressivement développé une activité de formation professionnelle, d'abord pour former ses propres téléprospecteurs, puis pour proposer des parcours à des salariés d'entreprises clientes. Cette évolution a rapidement fait apparaître deux difficultés majeures. La première est économique : le recours à des formateurs réduit fortement les marges réalisées sur l'activité de formation. La seconde est organisationnelle : la production et l'animation des formations reposent sur plusieurs intervenants humains, ce qui introduit des risques liés aux indisponibilités et au turnover.

L'objectif du projet est donc de concevoir une plateforme dans laquelle un professeur IA remplace totalement le rôle habituellement assuré par un formateur. Chaque semaine, ce professeur IA doit pouvoir animer une journée de formation structurée, présenter un cours à l'oral, s'appuyer sur des diapositives cohérentes avec son discours, et répondre aux questions des apprentis à partir du contenu réellement enseigné.

Deux contributions principales sont étudiées. La première est un pipeline de génération pédagogique composée d'une série d'étapes automatisées. A partir du simple code RNCP de la formation, la plateforme doit être capable de créer l'ensemble des éléments nécessaires au professeur IA : le contenu des différentes journées de cours, le déroulé de la journée, les scripts destinés à être lus à l'oral, ainsi que les diapositives utilisées pour accompagner son discours.

La seconde contribution concerne la capacité du professeur IA à interagir avec les apprentis. En effet, produire et délivrer un cours ne suffit pas à reproduire le rôle d'un formateur. Le professeur IA doit également être capable de répondre aux questions posées par les apprenants lors des temps d'échange prévus à cet effet. L'enjeu est alors de lui permettre de fournir des réponses cohérentes avec le contenu réellement enseigné pendant la formation, plutôt que de s'appuyer uniquement sur les connaissances générales d'un LLM. Pour répondre à ce besoin, une architecture de Retrieval-Augmented Generation (RAG) a été mise en place afin d'ancrer les réponses du professeur IA dans les supports réellement diffusés.

La démarche suivie repose sur une approche progressive consistant à décomposer les principales fonctions d'un professeur afin d'identifier celles pouvant être automatisées. L'objectif n'était pas de reproduire directement un formateur dans toute sa complexité, mais de comprendre comment ses différentes fonctions pouvaient être recréées à l'aide de l'intelligence artificielle. Ce mémoire montre ainsi comment il est possible de concevoir un professeur IA capable de produire ses propres supports de cours, d'animer une journée de formation et d'interagir avec les apprenants. Les résultats obtenus mettent en évidence la faisabilité de cette approche et les perspectives qu'elle ouvre pour l'automatisation de la formation professionnelle en ligne.

## 1. Introduction générale

### 1.1 Contexte

Nous vivons aujourd'hui dans un monde où le marché de l'énergie s'est libéralisé. En effet, jusqu'à la fin des années 1990, le marché de l'électricité était un monopole public. Cela signifie qu'EDF était quasiment le seul fournisseur d'électricité autorisé à vendre aux particuliers et aux entreprises.

Cependant, à partir de 1999, sous l'impulsion des directives européennes, le marché de l'énergie a été progressivement libéralisé. De nouveaux fournisseurs ont pu entrer sur le marché, les clients ont eu le droit de choisir leurs propres fournisseurs, et les fournisseurs qui avaient un monopole absolu (comme EDF avec l'électricité) ont dû ouvrir l'accès de leur réseau à leurs concurrents. C'est dans ce contexte particulier qu'en 2022, Valentin Guemache et Mehdi Rousselle décident de fonder leur entreprise.

Face à la libéralisation du marché, beaucoup d'entreprises manquent d'expertise pour identifier les meilleures offres. Le but des deux fondateurs avec Audits Énergies est donc d'accompagner ces professionnels dans la renégociation de leurs contrats.

C'est de cette manière qu'ils établissent leurs locaux à Noisy-Le-Grand, puis commencent à recruter. Un service RH est rapidement constitué, et plusieurs téléprospecteurs sont embauchés dans le but de démarcher les entreprises et de leur proposer un accompagnement dans la renégociation de leurs contrats d'énergie.

Mais recruter des téléprospecteurs ne suffit pas. Si ces derniers ont été sélectionnés pour leurs qualités relationnelles, ils doivent également être formés aux fondamentaux de la communication commerciale, aux spécificités réglementaires du secteur de l'énergie, et aux bonnes pratiques de la prospection. Un bon téléprospecteur est en effet celui qui maîtrise son sujet, sait adapter son discours à son interlocuteur et est capable d'être force de proposition face à un prospect. C'est pour répondre à ce besoin qu'en interne, un centre de formation a vu le jour.

Puis, assez rapidement, les fondateurs ont franchi une étape supplémentaire. Forts de leur expérience professionnelle et des formations qu'ils avaient dispensées en interne pour former leurs propres futurs salariés, les fondateurs ont développé une vraie expertise pédagogique dans des domaines précis : la vente, la téléprospection, la relation commerciale à distance, ou encore les spécificités du marché de l'énergie. C'est cette expertise qui les a conduits à se lancer sur le marché de la formation en ligne, donnant ainsi naissance à une seconde entreprise, « Sales Hacking ».

Le lien entre Audits Énergies et Sales Hacking est simple. Dans le cadre de son activité de courtage, Audits Énergies démarche des entreprises et les accompagne dans la renégociation de leurs contrats d'énergie. Une fois ces entreprises devenues clientes, une nouvelle opportunité se présente : leur proposer de former leurs employés via Sales Hacking. Concrètement, les salariés de ces entreprises partenaires intègrent une formation en alternance (au rythme d'un jour par semaine) au cours de laquelle ils acquièrent des compétences dans des domaines comme la vente, la relation client à distance ou la téléprospection, selon les besoins de leur secteur d'activité.

Ce modèle présente un double intérêt pour les dirigeants des entreprises clientes. D'un côté, il leur permet de faire monter en compétences leurs équipes sans les mobiliser à temps plein. D'autre part, il leur permet de bénéficier d'aides de l'État, réduisant ainsi le coût de leurs salariés. Audits Énergies et Sales Hacking forment ainsi un écosystème complémentaire, dans lequel l'activité de courtage alimente naturellement le développement de l'activité de formation.

C'est cette activité de formation qui constitue le cœur de ce mémoire. Son développement a rapidement fait apparaître deux difficultés majeures. La première est économique : le recours à des formateurs réduit fortement les marges réalisées sur l'activité de formation. La seconde est organisationnelle : la production et l'animation des formations reposent sur plusieurs intervenants humains, ce qui introduit des risques liés aux indisponibilités et au turnover.

C'est dans ce contexte qu'est née l'idée d'une plateforme de formation autonome alimentée par l'intelligence artificielle. L'ambition est de remplacer l'ensemble des interventions humaines nécessaires à la production et à l'animation des formations. La problématique de ce mémoire peut donc être formulée ainsi :

*Comment concevoir une plateforme de formation autonome alimentée par l'intelligence artificielle, capable de remplacer un formateur humain tout en garantissant la qualité pédagogique des contenus et de l'accompagnement des apprentis ?*

Pour répondre à cette problématique, trois objectifs principaux ont été définis. Le premier consiste à produire une formation longue et multisupport, comprenant du contenu écrit, des supports visuels et une version audio. Le deuxième consiste à rendre les journées de formation aussi proches que possible d'une formation animée par un professeur humain, avec une progression pédagogique, des transitions, des pauses et des temps d'échange. Le troisième consiste à permettre au professeur IA de répondre aux questions des apprentis de manière contextualisée, à partir du contenu réellement enseigné pendant la formation.

Pour atteindre ces objectifs, deux contributions principales sont étudiées dans ce mémoire. La première est un pipeline qui transforme un code RNCP en scripts de cours, supports visuels et contenus audio. Elle automatise la production de la formation et rend son organisation proche d'un déroulé humain. La seconde est une architecture de RAG qui permet au professeur IA de répondre aux questions des apprentis en s'appuyant sur les contenus réels de la formation plutôt que sur les seules connaissances générales d'un modèle de langage.

L'objectif n'est pas de présenter directement la solution finale retenue, mais de montrer la démarche qui a conduit à son élaboration. Comme dans de nombreux projets d'ingénierie, la solution finale est le résultat d'une succession d'expérimentations, d'observations et d'itérations.

### 1.2 Structure du mémoire

Ce mémoire est structuré en trois parties.

La première partie, la position du problème, présente le contexte dans lequel le projet est apparu. Elle revient sur l'évolution de l'entreprise, depuis son activité initiale de courtage en énergie jusqu'au développement de son activité de formation. Elle expose ensuite les limites économiques et organisationnelles rencontrées vis-à-vis de cette activité de formation, ainsi que la problématique qui a conduit à envisager une plateforme autonome alimentée par l'intelligence artificielle.

La deuxième partie, l'état de l'art, analyse les approches existantes permettant de répondre au problème posé. Elle étudie d'abord, à l'échelle macro, les solutions existantes de formation assistée par intelligence artificielle. Elle analyse ensuite, à l'échelle micro, les briques techniques nécessaires à la reproduction des fonctions d'un professeur pour créer notre professeur IA.

La troisième partie, l'étude originale, présente la solution conçue dans le cadre du projet. Elle détaille d'abord le pipeline de génération multi-support, ainsi que la manière dont il a été pensé. Elle présente ensuite l'architecture mise en place pour permettre au professeur IA de répondre aux questions des apprentis. Enfin, elle discute les apports, les limites et les pistes d'évolution de la solution.

## 2. Position du problème

### 2.1 D'une activité de formation à un problème d'industrialisation

J'ai rejoint Audits Énergies en février 2025, d'abord dans le cadre d'un stage, puis en alternance à partir de la rentrée suivante. Mes premières missions ne concernaient pas directement la formation : elles portaient sur des sujets liés à la donnée, principalement le scraping et l'enrichissement de données ainsi que la création d'automatisations au service de l'activité de courtage. C'est en juin 2025, alors que je travaillais déjà dans l'entreprise, que Sales Hacking a été créée. J'ai alors été amené à m'impliquer progressivement dans l'activité de formation, jusqu'à en devenir le principal acteur technique.

La création de Sales Hacking a marqué une évolution importante dans l'activité développée par les fondateurs d'Audits Énergies. Alors que l'entreprise était initialement spécialisée dans le courtage en énergie, elle a progressivement développé une activité de formation destinée aux métiers de la vente, de la téléprospection et de la relation client à distance.

Dans un premier temps, cette activité répondait principalement à un besoin interne. Les nouveaux collaborateurs devaient être formés aux spécificités du marché de l'énergie, aux techniques de communication commerciale et aux méthodes de prospection utilisées par l'entreprise. La formation concernait alors un nombre limité de personnes et reposait largement sur l'implication directe des fondateurs.

Le développement de Sales Hacking a cependant changé l'échelle du problème. L'objectif n'était plus seulement de former quelques collaborateurs, mais de proposer des parcours complets à destination de salariés d'entreprises clientes.

Cette évolution a naturellement entraîné une augmentation du volume de contenu à produire pour les formations. Les formations proposées par Sales Hacking durent généralement plusieurs mois. Les apprenants suivent une journée complète de cours par semaine, soit environ huit heures de formation. Certaines formations peuvent ainsi s'étendre sur près d'une année entière.

Tant que la formation concernait un nombre limité de collaborateurs en interne, cette organisation restait relativement simple à gérer. En revanche, lorsque plusieurs promotions suivent plusieurs formations en parallèle, les contraintes changent rapidement. Produire les contenus, maintenir leur cohérence et assurer leur diffusion devient une activité à part entière.

Former quelques salariés en interne et exploiter une activité de formation à plus grande échelle relèvent alors de logiques très différentes. Dans le premier cas, la transmission des connaissances repose principalement sur l'expérience des intervenants et sur des échanges directs avec les apprentis. Le formateur adapte naturellement son discours aux besoins du moment et les contenus évoluent au fil des situations rencontrées.

Dans le second cas, les exigences sont beaucoup plus importantes. Les contenus doivent être structurés, les objectifs pédagogiques clairement définis et les supports suffisamment cohérents pour être réutilisés auprès de plusieurs promotions. Il ne s'agit plus seulement de transmettre un savoir, mais de construire un véritable dispositif pédagogique capable de fonctionner dans la durée pour plusieurs formations et plusieurs promotions.

### 2.2 Les limites des approches reposant sur l'intervention humaine

La solution la plus naturelle consistait à faire appel à des formateurs spécialisés pour assurer les journées de formation. Cependant, cette solution s'est rapidement heurtée aux contraintes économiques et organisationnelles mentionnées précédemment.

Le dirigeant a alors eu l'ambition de remplacer les formateurs spécialisés par des professeurs IA. Un objectif aussi ambitieux, bien que parfaitement en adéquation avec notre époque et les progrès récents de l'intelligence artificielle, ne pouvait cependant pas être atteint du jour au lendemain.

En attendant de pouvoir concrétiser cette vision, il a donc commencé à réfléchir à une autre approche pour éviter de recruter un formateur onéreux. Une première solution a consisté à préparer les cours à l'avance puis à les diffuser sous forme d'audios sur la plateforme. Les apprenants ne suivaient donc plus un cours animé en direct, mais un contenu déjà produit et mis à disposition le jour de la formation.

C'est dans ce cadre que j'ai conçu, durant l'été 2025, une première version de la plateforme. Celle-ci ne comportait pas encore de professeur IA : elle servait à héberger les audios préparés à l'avance et à les enchaîner automatiquement le jour de la formation, de manière à reproduire le déroulé d'une journée en « faux direct ». Cette première version reposait donc encore entièrement sur le travail humain réalisé en amont, qu'il s'agisse de la rédaction des contenus ou de l'enregistrement des voix off.

Pour produire ces contenus, le dirigeant avait conçu une série de prompts, de consignes et de directives pédagogiques basés sur son expérience métier. L'idée était qu'une même personne puisse utiliser l'intelligence artificielle pour générer elle-même les cours puis enregistrer les audios correspondants. Cette personne n'avait pas besoin d'être spécialiste du domaine enseigné : il lui suffisait, en théorie, de suivre la méthode définie en amont par le dirigeant, M. Rousselle.

Sur le papier, cette approche permettait de réduire considérablement les coûts. Dans la pratique, elle s'est révélée plus difficile à mettre en œuvre. Malgré les prompts et les consignes détaillées, les personnes recrutées ne parvenaient pas à s'approprier suffisamment le contexte de l'entreprise pour produire les cours de manière autonome.

Pour répondre à cette difficulté, une deuxième organisation a été mise en place. La génération des cours a été confiée à une personne interne à l'entreprise, déjà familière avec son activité et ses méthodes de travail. En s'appuyant sur les prompts et les directives définis par le dirigeant, cette personne utilisait l'intelligence artificielle pour produire les contenus pédagogiques. Une personne recrutée pour être voix off uniquement se chargeait ensuite de leur lecture et de la production des fichiers audio.

Cette nouvelle manière de fonctionner a en partie permis de réduire les coûts liés au recrutement d'un formateur spécialisé.

Cependant, elle n'a fait qu'amplifier les contraintes organisationnelles et opérationnelles. Les cours devaient être créés, transmis à la voix off, enregistrés, récupérés, vérifiés puis intégrés à la plateforme. Chaque étape nécessitait des échanges, des validations et des relances. Une indisponibilité, un retard ou un oubli pouvait retarder tout le bon déroulé de la formation.

À cela s'ajoutait un autre facteur : le turnover. Les personnes recrutées pour assurer les voix off ne restaient pas toujours sur la durée. Lorsqu'un intervenant quittait son poste, il fallait en recruter un nouveau, lui réexpliquer le fonctionnement de l'organisation mise en place, les outils utilisés et les attentes de l'entreprise. Cette situation représentait une charge supplémentaire et introduisait une nouvelle forme d'instabilité dans le processus. A plusieurs reprises, l'entreprise s'est retrouvée dans une situation où aucun intervenant n'était disponible pour préparer les contenus audios de la semaine suivante, alors même que les formations devaient continuer à être assurées.

Désormais, la principale difficulté résidait uniquement dans la dépendance à de nombreuses interventions humaines pour produire et diffuser les formations. Chaque nouvel intervenant ajoutait une étape supplémentaire dans le processus et introduisait de nouvelles sources de friction : échanges entre les différents acteurs, validations, corrections, relances, retards dans l'envoi des audios ou difficultés de coordination. Plus le nombre d'intervenants augmentait, plus l'organisation devenait complexe à piloter et plus le risque de perturber le déroulement de la formation augmentait.

C'est à ce moment que l'idée du professeur IA a commencé à prendre une place centrale. Il devenait nécessaire de réaliser ce projet.

### 2.3 Vers la vision d'un professeur IA

Cette vision (remplacer les formateurs spécialisés par des professeurs IA) était celle du dirigeant, M. Mehdi Rousselle, depuis le départ. Elle est toutefois rapidement devenue une vision partagée : ayant conçu la plateforme depuis sa première version, j'en comprenais pleinement les tenants et les aboutissants, ce qui m'a permis d'être force de proposition sur la direction technique à donner au projet.

Cependant, une telle vision restait au départ largement théorique. Rien ne permettait d'affirmer qu'il était réellement possible de construire un professeur IA capable d'assurer plusieurs heures de formation, de produire ses contenus, de générer ses supports pédagogiques et d'accompagner les apprenants tout au long de leur parcours. L'objectif était séduisant, mais il était encore difficile de distinguer ce qui relevait d'une possibilité réelle de ce qui relevait simplement d'une promesse souvent associée aux nouvelles technologies.

C'est à partir de février 2026 que j'ai repris le projet, cette fois avec un objectif précis : concevoir et développer ce professeur IA. Sur ce périmètre, j'étais le seul concepteur et développeur. L'architecture, les choix d'implémentation et l'étude de leur faisabilité ont été réalisés et orchestrés en autonomie. Mon tuteur, M. Rousselle, n'intervenait pas sur les choix techniques eux-mêmes : une fois ces choix arrêtés, je les lui présentais afin qu'il les valide et vérifie leur cohérence avec sa vision produit et ses plans initiaux. Ce fonctionnement m'a laissé une large autonomie de conception, tout en garantissant l'alignement du projet avec les objectifs de l'entreprise.

Avec le recul, les différentes expérimentations décrites précédemment ont profondément influencé ma manière d'aborder le problème. Les solutions successivement mises en place pour contourner les contraintes économiques et opérationnelles n'ont pas seulement permis d'assurer la continuité des formations : elles ont aussi structuré ma réflexion sur la manière dont un professeur IA pouvait être conçu. Un constat s'est progressivement imposé : lorsqu'une tâche devient trop complexe, il est souvent plus efficace de la décomposer en plusieurs tâches plus simples et plus spécialisées. C'est précisément ce qui distinguait la tentative reposant sur une personne unique, incapable de cumuler à elle seule toutes les fonctions attendues, de l'organisation à deux rôles, plus efficace parce que plus spécialisée.

Progressivement, une idée s'est donc imposée : pour construire un professeur IA, il n'était peut-être pas nécessaire de chercher à reproduire directement un formateur dans toute sa complexité. Il fallait d'abord comprendre les différentes fonctions qu'il assure au quotidien, les décomposer, puis réfléchir à la manière dont chacune d'elles pouvait être automatisée.

Ce changement de perspective a profondément influencé la suite du projet. Je ne cherchais plus à créer directement un professeur IA, mais à identifier les différents mécanismes, les différentes fonctions, qui permettent aujourd'hui à un formateur d'assurer une formation, afin de comprendre comment ils pourraient être reproduits à l'aide de l'intelligence artificielle.

## 3. État de l'art

Avant de concevoir un professeur IA, il faut se poser une question simple : qu'est-ce qu'un professeur fait réellement ? Et surtout : est-ce que quelqu'un l'a déjà fait à sa place ? C'est à ces deux questions que cet état de l'art cherche à répondre.

Pour y répondre, l'analyse est menée à deux niveaux. D'abord à l'échelle macro : est-ce que les solutions existantes de formation assistée par IA ont déjà résolu le problème en entier ? Ensuite à l'échelle micro : puisque personne ne l'a fait, quelles sont les briques techniques disponibles pour reproduire chacune des deux fonctions essentielles d'un formateur à savoir produire et délivrer un cours, puis interagir avec eux.

### 3.1 Le problème a-t-il déjà été résolu ?

L'apparition des LLM a favorisé le développement de nombreuses plateformes spécialisées dans la création de contenus pédagogiques. Des solutions comme Easygenerator, Learn Worlds Al ou Coursebox permettent aujourd'hui de générer des cours, des quiz, des évaluations ou des supports pédagogiques à partir d'un document ou d'une description. Learn Worlds présente par exemple son assistant IA comme un outil capable de générer des plans de cours, des évaluations et des contenus pédagogiques. Coursebox met également en avant des fonctionnalités comme la génération de quiz, de vidéos, de flashcards, de tutorat IA ou encore d'évaluation automatique.

Parallèlement, certaines plateformes ont intégré des assistants conversationnels capables d'accompagner les apprenants pendant leur formation. Khanmigo, développé par Khan Academy, est présenté comme un tuteur personnel et un assistant pédagogique capable de guider l'apprenti sans simplement lui donner la réponse.

Ces outils permettent d'automatiser une partie importante du travail de conception et d'accompagnement pédagogique. Ils répondent principalement à une logique d'e-learning, dans laquelle les apprenants suivent des modules, des vidéos ou des ressources pédagogiques à leur propre rythme.

Cependant, ces solutions ne répondent pas directement au besoin étudié dans ce mémoire. Leur objectif est de produire des contenus, d'assister les concepteurs de formation ou d'accompagner les apprentis, mais non de reproduire le comportement complet d'un professeur assurant une journée entière de formation. Elles ne sont généralement pas conçues pour animer une formation complète en visioconférence, avec un déroulé pédagogique structuré, une présentation progressive du contenu, la gestion des différentes séquences de cours et des phases de questions-réponses au sein d'un même système.

C'est précisément là que se situe le besoin de Sales Hacking : il ne s'agit pas de proposer des modules e-learning qu'un apprenti pourrait suivre librement, mais de reproduire une journée de formation animée de bout en bout, ce qu'aucune de ces plateformes ne permet de faire.

L'analyse à l'échelle macro montre donc que les solutions existantes automatisent certaines fonctions utiles dans le cadre de la formation en ligne, mais qu'elles ne répondent pas au problème étudié dans ce mémoire.

Il devient alors nécessaire de descendre à une échelle plus fine, afin d'étudier les briques techniques permettant de reproduire individuellement ces différentes fonctions.

### 3.2 Première fonction: produire et délivrer un cours

Un professeur ne génère pas juste du texte. Il parle, il montre, il structure. Reproduire cette fonction suppose trois choses simultanément : produire un contenu écrit cohérent, des supports visuels alignés, et une version orale adaptée à l'écoute. Et c'est là que les choses se compliquent.

Produire un cours exploitable implique de générer un contenu écrit structuré, des supports visuels cohérents et une version orale du cours. Ces différents supports doivent également rester alignés entre eux afin de suivre une même progression pédagogique.

#### 3.2.1 La production pédagogique multisupport synchronisée

Aujourd'hui, plusieurs outils permettent de produire certaines composantes de ce besoin. Les LLM peuvent générer du contenu écrit, des outils spécialisés peuvent créer des présentations, et les technologies de synthèse vocale permettent de transformer un texte en voix. Cependant, ces outils sont généralement pensés pour produire une brique spécifique ou un contenu ponctuel : un texte, une présentation ou une courte vidéo.

La difficulté apparaît lorsque l'on cherche à produire un parcours long et structuré tout en conservant une cohérence entre le texte, les supports visuels et l'audio. À notre connaissance, et parmi les solutions étudiées, aucun outil ne propose aujourd'hui de produire un tel ensemble. Il devient alors nécessaire d'analyser séparément les principales briques existantes : la génération de contenu écrit, la génération de supports visuels et la génération vocale.

#### 3.2.2 La génération de contenu écrit par LLM

Les modèles récents peuvent accepter des volumes d'entrée et de sortie beaucoup plus importants qu'auparavant, ce qui permet d'intégrer davantage de consignes, d'informations, et d'obtenir des réponses encore plus longues et détaillées. Cependant, plusieurs limites apparaissent.

En effet, même lorsque les LLM acceptent des contextes longs, cela ne signifie pas qu'ils exploitent parfaitement toutes les informations fournies. Les travaux sur le phénomène *Lost in the Middle* montrent que les modèles peuvent être moins performants lorsque l'information pertinente se situe au milieu d'un long contexte, même lorsque celui-ci entre techniquement dans la fenêtre de contexte du modèle.

Dans le cas d'un référentiel de titre professionnel, cela signifie que le modèle doit non seulement recevoir un volume important d'informations, mais aussi les hiérarchiser, les interpréter et les transformer en progression pédagogique cohérente.

À cette contrainte d'entrée s'ajoute une contrainte de sortie. Les modèles disposent également d'une limite sur le volume de texte généré en une seule réponse. Or, une formation longue d'un an peut nécessiter une production de plusieurs milliers de pages. A titre d'ordre de grandeur, en retenant une hypothèse d'environ 500 mots par page, 2 000 pages représentent déjà environ 1,3 à 1,5 million de tokens, tandis que 3 000 pages peuvent représenter environ 2 à 2,25 millions de tokens. Ces volumes sont très supérieurs aux volumes habituellement générables en une seule réponse par les API de modèles de langage.

La génération directe par prompt constitue ainsi une approche simple et puissante pour produire du contenu pédagogique. Elle offre un point d'entrée efficace pour générer rapidement des contenus, tout en soulevant des enjeux importants lorsque la formation à produire devient longue, structurée et dépendante d'un référentiel documentaire volumineux.

#### 3.2.3 La génération de supports visuels

La production d'un cours ne repose pas uniquement sur le texte. Au sein d'une formation, les supports visuels occupent une place importante. Ils permettent de structurer l'attention des apprenants, d'accompagner les explications du formateur, de résumer les notions importantes et de rendre certaines idées plus faciles à comprendre.

Plusieurs outils permettent aujourd'hui de générer automatiquement des présentations à partir d'un prompt. Cette approche permet de gagner du temps. Elle peut par exemple être utile pour produire une présentation courte.

Cependant, la génération de supports visuels ne répond qu'à une partie du besoin pédagogique. Dans le cadre d'un cours, les diapositives ne doivent pas seulement être esthétiques ou bien organisées. Elles doivent être alignées avec le contenu du cours, apparaître au bon moment et accompagner précisément les explications du formateur.

Une présentation générée automatiquement peut donc être correcte sur le plan visuel tout en restant trop générale, trop synthétique ou insuffisamment liée au déroulé pédagogique. Le problème n'est pas uniquement de créer des diapositives, mais de produire des supports capables d'accompagner un contenu aussi long et aussi structuré.

#### 3.2.4 La génération vocale

Une autre composante importante de la délivrance d'un cours concerne l'oralisation du contenu. Les progrès récents de la synthèse vocale ont considérablement réduit l'écart entre voix artificielle et voix humaine. Les modèles les plus récents permettent désormais de contrôler finement la manière dont un texte est interprété grâce à l'utilisation de tags ou d'instructions décrivant le ton, l'émotion, le rythme, les pauses ou encore l'intention de la voix.

Ils peuvent également reproduire les hésitations, les rires, les soupirs ou d'autres expressions vocales contribuant au réalisme de la synthèse vocale.

La qualité finale dépend toutefois toujours du texte fourni au moteur vocal : même la meilleure voix ne peut compenser un contenu mal structuré ou insuffisamment adapté à l'oral.

#### 3.2.5 Synthèse critique

L'analyse des approches existantes montre que les briques nécessaires à la production d'un cours existent en partie. Cependant, ces briques répondent généralement à des besoins partiels. La génération textuelle soulève des enjeux de longueur, de contexte, de cohérence et de volume de sortie. La génération de supports visuels pose la question de l'alignement avec le discours pédagogique.

La difficulté principale réside donc dans la coordination de ces différents supports.

### 3.3 Deuxième fonction: répondre aux questions des apprenants

Produire un cours ne suffit pas. Un professeur répond aussi. Et là, le problème est d'une nature différente : il ne s'agit plus de générer du contenu, mais de rester ancré dans ce qui a été enseigné. Comment faire répondre un modèle non pas à partir de ce qu'il sait en général, mais à partir de ce qu'il a dit ce matin ?

Plusieurs approches existent aujourd'hui pour reproduire cette fonction. Les principales sont le prompt engineering, le fine-tuning et les architectures de type Retrieval-Augmented Generation.

#### 3.3.1 Le prompt engineering

Le prompt engineering consiste à guider le comportement d'un modèle à l'aide d'instructions détaillées. Cette approche permet notamment de définir un rôle, un ton ou certaines règles de réponse.

Dans le cadre d'un assistant pédagogique, il est possible d'utiliser cette méthode pour demander au modèle de répondre comme un professeur, de rester concis ou de respecter un certain style pédagogique. Il est également possible de fournir au modèle des éléments de contexte directement dans le prompt.

Cette approche présente plusieurs avantages. Elle est simple à mettre en place, ne nécessite pas de modifier le modèle et permet d'ajuster rapidement le comportement de l'assistant.

Cependant, lorsque les documents de référence deviennent volumineux ou évoluent régulièrement, la gestion du contexte devient plus complexe. Il faut alors transmettre au modèle les informations utiles à chaque requête. Lorsque les contenus représentent plusieurs heures de formation, la quantité d'informations à injecter dans le prompt augmente fortement, ce qui peut accroître le coût des requêtes, le temps de traitement et le risque que certaines informations importantes soient mal prises en compte.

Le prompt engineering constitue donc une approche efficace pour encadrer le comportement d'un assistant, mais il présente des limites lorsque la réponse doit s'appuyer sur un corpus documentaire long et régulièrement mis à jour.

#### 3.3.2 Le fine-tuning

Le fine-tuning consiste à adapter un LLM en modifiant une partie de ses paramètres internes à partir d'exemples représentatifs. Cette approche poursuit généralement deux objectifs principaux : reproduire un comportement particulier ou spécialiser le modèle sur un domaine spécifique.

Le premier usage du fine-tuning consiste à modifier le comportement du modèle. Il peut être utilisé pour reproduire un style de rédaction, une méthode de raisonnement ou une manière particulière de répondre. Dans le domaine de la formation, il serait par exemple possible d'entraîner un modèle à partir d'un ensemble de cours rédigés par un même formateur afin de reproduire sa manière d'expliquer les concepts, de construire ses exemples ou d'interagir avec les apprenants.

Le second usage consiste à spécialiser le modèle sur un domaine de connaissances particulier. En exposant le modèle à des données spécialisées, il est possible d'améliorer ses performances sur certains sujets métier et de renforcer sa maîtrise d'un vocabulaire ou de concepts spécifiques.

Cette approche présente plusieurs avantages. Elle permet de stabiliser le comportement du modèle et d'améliorer ses performances sur un domaine donné.

Cependant, le fine-tuning nécessite la constitution d'un jeu de données de qualité ainsi que des ressources de calcul dédiées à l'entraînement. Des techniques plus légères comme LoRA, ou encore QLORA, diminuent ces coûts en limitant le nombre de paramètres à adapter, tout en conservant une partie importante des bénéfices du fine-tuning classique.

Enfin, les connaissances acquises lors du fine-tuning restent intégrées aux paramètres du modèle. Lorsque les documents de référence évoluent régulièrement ou que le contenu à prendre en compte change fréquemment, la mise à jour du modèle peut devenir plus complexe que dans d'autres approches fondées.

Le fine-tuning constitue donc une approche puissante pour adapter le comportement d'un modèle ou renforcer son expertise dans un domaine particulier. Son intérêt dépend principalement de la stabilité des connaissances à intégrer et du niveau de personnalisation recherché.

#### 3.3.3 Le Retrieval-Augmented Generation

Le Retrieval-Augmented Generation, plus communément appelé RAG, est une approche conçue pour répondre à certaines limites des LLM lorsqu'ils doivent produire des réponses fondées sur des documents précis.

Les LLM possèdent une grande quantité de connaissances générales acquises lors de leur entraînement. Cependant, ils ne disposent pas nécessairement d'informations à jour et ne sont pas toujours capables de répondre précisément en adéquation avec le contenu d'un ensemble de documents spécifiques.

Pour répondre à cette problématique, les architectures RAG associent un système de recherche documentaire à un LLM. Lorsqu'un utilisateur pose une question, le système commence par rechercher dans une base documentaire les passages les plus pertinents. Ces informations sont ensuite transmises au modèle afin qu'il puisse générer une réponse en s'appuyant sur le contenu récupéré.

Cette approche permet d'utiliser des documents régulièrement mis à jour sans avoir à réentraîner le modèle.

Cependant, le RAG présente aussi certaines limites. La qualité des réponses dépend directement de la qualité des documents disponibles et de la capacité du système à retrouver les informations pertinentes. Une récupération incomplète ou incorrecte peut conduire le modèle à produire une réponse partiellement correcte ou incomplète.

#### 3.3.4 Les principales variantes des architectures RAG

Les architectures RAG ont connu de nombreuses évolutions depuis leur introduction. Elles se distinguent principalement par leur manière de rechercher et de sélectionner les documents transmis au modèle de langage.

Certaines approches reposent sur une recherche lexicale, fondée sur les mots-clés présents dans les documents. D'autres utilisent une recherche vectorielle, qui s'appuie sur la similarité sémantique entre la requête et les documents afin de retrouver des passages proches par le sens.

De nombreuses solutions modernes combinent ces deux mécanismes dans des architectures dites hybrides, afin de bénéficier à la fois de la précision de la recherche lexicale et de la flexibilité de la recherche sémantique.

Certaines architectures ajoutent également des étapes complémentaires, comme le reranking des résultats ou la reformulation automatique des requêtes, dans le but d'améliorer la pertinence des documents récupérés avant leur transmission au modèle de langage.

Malgré leurs différences, ces variantes poursuivent toutes le même objectif : fournir au modèle les informations les plus pertinentes possibles afin d'améliorer la qualité et la fiabilité des réponses générées.

#### 3.3.5 Synthèse critique

Les approches étudiées permettent toutes d'améliorer la capacité d'un assistant à répondre aux questions des utilisateurs. Le prompt engineering agit principalement sur les instructions données au modèle. Le fine-tuning agit directement sur les paramètres du modèle afin d'adapter son comportement ou ses connaissances. Les architectures RAG s'appuient quant à elles sur une base de documents externe afin d'inscrire les réponses du LLM dans un cadre précis.

Ces approches répondent donc à des problématiques différentes et présentent chacune des avantages ainsi que des limites. Leur étude permet de mieux comprendre les stratégies existantes pour reproduire la capacité d'un professeur à répondre aux questions des apprenants.

### 3.4 Synthèse générale de l'état de l'art

Les briques existent et les approches existent.

L'analyse à l'échelle micro montre de son côté que les briques techniques nécessaires existent en partie. Les LLM permettent de générer du contenu, les outils de présentation permettent de produire des supports visuels, les systèmes de synthèse vocale permettent de transformer du texte en audio et les architectures RAG permettent de contextualiser les réponses à partir d'une base documentaire.

La limite principale réside dans l'articulation de ces briques. Chaque technologie répond à une fonction particulière, mais leur coordination au sein d'un même système reste une difficulté importante. Pour Sales Hacking, aucune de ces approches prise isolément ne suffit : reproduire un formateur suppose à la fois de coordonner la production multisupport d'un cours et d'ancrer les réponses dans le contenu réellement enseigné. C'est précisément ce point qui justifie l'étude originale présentée dans la partie suivante.

### 3.5 Tableau récapitulatif des approches existantes

Le tableau suivant récapitule l'ensemble des approches évoquées dans cet état de l'art, leurs apports, leurs limites et leur pertinence au regard du besoin de la plateforme.

| 

| **Approche / Outil** | **Apports** | **Limites** | **Pertinence pour le besoin** | 
| **Plateformes de création de contenus** (Easygenerator, Learn Worlds Al, Coursebox) | Génèrent cours, quiz, évaluations et supports à partir d'un sujet ou d'un document. | Logique d'e-learning pour suivre un parcours à son rythme. | Couvrent la création de contenus, mais pas la délivrance animée visée. | 
| **Assistants conversationnels d'accompagnement** (Khanmigo) | Tutorat personnalisé qui guide l'apprenant sans donner directement la réponse. | Centrés sur l'accompagnement individuel. | Utile seulement pour le temps de questions-réponses. | 
| **Génération de contenu écrit** (LLM) | Produit rapidement du texte pédagogique (fenêtres de contexte croissantes). | Cohérence difficile sur de longs contenus, « lost in the middle », limite de volume et de cohérence en sortie. | Insuffisant seul et en l'état pour notre projet. | 
| **Génération de supports visuels** (outils de présentation) | Crée rapidement des diapositives à partir d'un prompt, d'un plan ou d'un document. | Slides souvent génériques, et non synchronisées avec le discours et le déroulé. | Doivent être synchronisées au cours, ce que les outils ne font pas nativement. | 
| **Génération vocale** (synthèse vocale TTS) | Transforme un script en voix humaine. L'écart entre voix artificielle et humaine s'est réduit. | Qualité dépendante du script : un texte mal adapté à l'oral donne un audio difficile à suivre. | Brique de délivrance, entièrement tributaire de la qualité du texte produit en amont. | 
| **Prompt engineering** | Encadre le comportement du modèle ; simple et rapide à mettre en place. | Gestion du contexte coûteuse et fragile lorsque le corpus est long ou évolutif. | Insuffisant pour garantir l'ancrage des réponses dans le contenu exact du cours. | 
| **Fine-tuning** (et LoRA/ QLORA) | Adapte le comportement ou spécialise le modèle sur un domaine. | Jeu de données et calcul nécessaires : ré-entraînement à chaque mise à jour. | Peu adapté à des contenus changeant d'une formation à l'autre. Peu adapté pour un besoin commercial. | 
| **RAG et variantes** (lexicale/BM25, vectorielle, hybride, RRF, etc.) | Les réponses s'inscrivent dans un cadre précis en s'appuyant sur une base documentaire. | Qualité dépendante de l'étape de récupération des passages pertinents. | Adapté au besoin : répondre à partir du contenu réellement enseigné dans la formation. | 

## 4. Étude originale

### 4.1 Première fonction: produire et délivrer un cours

Pour mener à bien ce projet, la fonction principale à reproduire était celle d'un professeur capable de produire et de délivrer un cours en s'appuyant sur des supports visuels.

L'état de l'art a montré que les briques nécessaires à cette fonction existent en partie. Les LLM peuvent produire du contenu écrit, les outils de synthèse vocale peuvent transformer ce contenu en audio, et les outils de présentation peuvent générer des supports visuels. Cependant, ces briques sont généralement pensées séparément.

La difficulté principale de notre projet consiste donc à les coordonner dans une formation longue, structurée et exploitable. Pour répondre à cette difficulté, l'approche retenue a été de concevoir un pipeline de génération multi-support personnalisé. La suite de cette partie présente progressivement la logique de ce pipeline.

#### 4.1.1 Une logique de décomposition inspirée du fonctionnement humain

La conception du pipeline est partie d'une observation simple : pour automatiser une fonction humaine complexe, il faut d'abord comprendre comment cette fonction est réalisée, puis la décomposer en tâches plus simples. Cette décomposition s'est faite selon deux axes complémentaires, qui serviront de fil conducteur à toute cette partie. Un premier axe, une décomposition horizontale, découpe la journée dans le temps en séquences audios successives (cours, questions-réponses, pauses). Un second axe, une décomposition cette fois-ci verticale du problème, descend à l'intérieur de chaque séquence audio pour construire progressivement le contenu qui la remplit, du code RNCP jusqu'au texte final. La suite présente ces deux axes l'un après l'autre.

La première décision d'architecture a consisté à ne pas produire d'un seul bloc le texte d'une journée entière de formation, ni celui d'une formation complète. En effet, dans ce projet, le texte n'est pas seulement pensé comme un contenu pédagogique : il est aussi conçu comme un futur contenu audio.

Il n'était donc pas pertinent de produire un fichier audio unique de plusieurs heures pour une journée de formation. Le texte correspondant aurait été difficile à générer, à structurer, à calibrer et à contrôler.

J'ai donc fait le choix de découper une journée de formation en plusieurs séquences audio : des temps de cours, d'environ 45 minutes à 1 heure ; des temps de questions-réponses, d'environ 10 minutes ; et des pauses, dont une pause déjeuner.

*Figure 1 - Découpage d'une journée de formation en séquences audio: temps de cours, de questions-réponses et pauses.* *Figure 2 - Enchaînement des séquences audios d'une journée et transitions entre cours, questions-réponses et pause.*

Ces fichiers audios ne sont toutefois pas pensés comme des contenus indépendants que l'apprenti lancerait librement. Ils sont intégrés de manière algorithmique dans un déroulé journalier de telle sorte qu'ils soient joués successivement et automatiquement par la plateforme, afin de reproduire le fonctionnement d'une journée de formation en direct.

À la fin de chacun de ces audios, le script prévoit une courte conclusion, puis une phrase de transition vers le moment suivant de la journée. Ainsi, à la fin d'un vocal de cours, cette transition annonce l'ouverture d'un temps de questions-réponses. À la fin du fichier audio prévu pour ce temps d'échange, une nouvelle transition annonce la pause. De la même manière, à la fin du fichier audio de pause, une phrase de reprise réintroduit naturellement la séquence de cours suivante.

Ce découpage répond à un double objectif. Le premier est fonctionnel : il donne à l'apprenti l'impression de suivre un cours en direct, puisque tous les audios s'enchaînent naturellement. Le second est technique : en découpant la journée en audios de quarante-cinq minutes à une heure, le calibrage du volume final du texte ainsi que son contenu restent plus maitrisés.

En effet, ce découpage permet de guider plus précisément le contenu attendu pour chaque séquence. Il a également permis d'intégrer une contrainte de durée dans la génération du texte. A partir de tests réalisés avec la voix choisie dans l'outil de synthèse vocale, j'ai pu estimer un nombre moyen de mots par minute. Ce ratio a ensuite été utilisé pour définir un budget de mots par séquence proportionnellement à la durée de chaque audio, afin que chaque texte généré corresponde autant que possible à la durée audio attendue.

Ce premier découpage constitue l'axe horizontal annoncé plus haut : il organise la journée dans le temps, en séparant les séquences de cours, les temps de questions-réponses et les pauses.

Mais cet axe horizontal ne fait que dessiner des emplacements vides. Ainsi, une fois ces emplacements définis, il reste à produire, pour chacun d'eux, un texte suffisamment structuré, cohérent et adapté à l'oral. C'est tout l'objet de l'axe vertical : déterminer comment construire progressivement le contenu qui remplira chaque séquence audio.

C'est cette seconde logique de décomposition qui a guidé la première version du pipeline de génération de la formation.

#### 4.1.2 Première version du pipeline: du REAC au remplissage des audios

Une fois la journée découpée en séquences audio, l'objectif devenait plus précis : permettre, à partir seulement du code RNCP d'une formation, de générer progressivement les textes destinés à remplir chacun des 7 audios de cours de la journée.

Cette première version du pipeline suivait une logique simple : partir d'une source officielle, l'enrichir, construire une vision globale de la formation, puis descendre progressivement jusqu'au contenu attendu pour chaque audio.

*Figure 3 - Première version du pipeline de génération, du code RNCP jusqu'aux audios.*

**Étape 1 - Récupérer la source officielle associé au contenu du titre professionnel** À partir du code RNCP, le système récupérait le REAC associé au titre professionnel. Ce document constitue le référentiel emploi, activités et compétences : il décrit les activités types, les compétences attendues, les savoir-faire et les éléments réglementaires liés au titre. Cependant, le REAC n'est pas directement un cours. C'est un document officiel, dense, réglementaire et peu pédagogique. Il permet de savoir ce que la formation doit couvrir, mais il ne fournit pas un plan à suivre, des exemples ou des explications prêtes à l'emploi.

**Étape 2 - Transformer le REAC en une base de connaissances** Cette base est construite en deux temps. Le système extrait d'abord les compétences du REAC. Ensuite, chaque compétence est enrichie par le LLM sous forme de matière pédagogique : définitions, cas fictifs, pièges fréquents, vocabulaire métier et contexte terrain. Le REAC sert donc de point d'ancrage officiel, tandis que la base de connaissances fournit une matière plus pédagogique pour alimenter la future génération.

**Étape 3 - Générer le programme global de formation** À partir de cette base enrichie, le système génère un programme global donnant une vision d'ensemble du parcours sur plusieurs mois : grandes lignes de chaque journée, thèmes principaux, compétences visées et notions à traiter. Il ne s'agit pas encore d'écrire les cours, mais de définir l'organisation générale de la formation. *Figure 4 - Exemple de programme de formation généré à partir du REAC.*

**Étape 4 - Générer le programme journalier** Le pipeline descend ensuite à un niveau plus précis : chaque journée est divisée en 7 grands chapitres, correspondant chacun à l'un des 7 audios de cours. L'objectif n'est pas encore de rédiger le texte, mais de définir ce que chaque audio devra traiter. Par exemple, le premier chapitre peut introduire le titre professionnel et le contexte métier, tandis que les suivants développent des thèmes plus précis : accueil client, diagnostic du besoin, accompagnement, gestion des situations difficiles, etc. Chaque chapitre possède ainsi un titre et un descriptif suffisamment précis pour guider la génération du texte. *Figure 5 - Découpage d'une journée en sept chapitres, correspondant chacun à un audio de cours.*

**Étape 5 - Générer le texte associé à chaque audio.** Chaque chapitre dispose d'un thème, d'un descriptif et d'un budget de mots calculé selon la durée audio attendue. Le LLM reçoit donc un cadre précis : ce qu'il doit traiter, le budget de mots et la position du chapitre dans la journée. Cette notion de position est importante : le comportement attendu n'est pas le même pour le premier audio de toute la formation (qui accueille les apprenants et présente le parcours), pour le premier audio d'une journée classique (qui introduit le programme du jour) ou pour un audio de milieu de journée. Chaque audio de cours doit en outre prévoir une conclusion, un court récapitulatif et une transition vers la séquence suivante.

**Étape 6 - Ajouter les premiers garde-fous.** Les textes obtenus présentaient encore des défauts : dépassement du volume attendu, manque de précision, formulations trop affirmatives ou éléments non souhaités. Deux premiers garde-fous ont donc été ajoutés. Le premier concernait le budget de mots, en identifiant les textes trop courts ou trop longs par rapport au volume de mots attendu. Le second concernait la micro-conformité : reformuler des passages problématiques (par exemple une statistique inventée comme « 80% des clients réagissent ainsi »), et adapter certaines formulations à l'oral en évitant les tournures trop écrites mal restituées par la synthèse vocale.

**Étape 7 - Associer le texte généré aux templates de slides** Une fois les textes validés par les garde-fous, le pipeline tentait de générer les supports visuels associés. Pour cela, le texte correspondant à chaque audio était analysé afin d'identifier les passages pouvant être illustrés par une slide. Chaque passage identifié était ensuite associé à une slide parmi notre deck de templates. Par exemple, une définition pouvait être reliée à un modèle de type « concept clé », tandis qu'une liste d'étapes pouvait être associée à un modèle de checklist ou de procédure.

Cette première version permettait de valider l'idée générale du pipeline. Elle a cependant fait apparaître quatre limites principales.

* **Limite 1: Des textes encore trop libres** Même en respectant le thème imposé, les textes pouvaient manquer de clarté. Le contenu abordait bien le sujet, mais le fil pédagogique n'était pas toujours assez explicite.

* **Limite 2 - Des garde-fous appliqués sur des volumes encore trop longs.** Appliquées sur des textes de 45 minutes à 1 heure d'audio, les garde-fous ne corrigeaient pas toujours l'ensemble des erreurs.

* **Limite 3 - Un calibrage encore imparfait** Même avec un budget de mots défini, et des gardes-fous, le LLM produisait parfois un texte trop court ou trop long. Or le texte devait ensuite être transformé en audio : un mauvais calibrage entraînait un écart direct entre la durée attendue et la durée réelle.

* **Limite 4 - La difficulté d'intégrer les supports visuels.** La limite la plus importante. L'approche consistait à générer le texte, puis à demander à un LLM d'associer certaines parties à des templates de slides. Cette méthode restait fragile : certaines portions n'étaient associées à aucune slide, d'autres à un template peu adapté, et les transitions entre discours et supports n'étaient pas toujours naturelles.

Cette dernière limite a marqué une étape importante dans la réflexion. La difficulté n'était plus seulement de générer du texte ou de l'audio, mais de coordonner correctement le texte et l'audio avec les supports visuels. C'est ce constat qui a conduit à faire évoluer le pipeline vers une version plus structurée.

#### 4.1.3 Évolution vers un pipeline structuré par plan

Les limites observées dans la première version ont conduit à faire évoluer l'architecture du pipeline. La difficulté principale concernait l'intégration des supports visuels : dans la première version, le texte était généré d'abord, puis les diapositives associées après coup, ce qui rendait difficile l'alignement entre le cours et les slides.

Face à ces quatre limites, je suis parvenu à trouver une solution capable de répondre à l'ensemble d'entre elles d'un coup. Cette solution repose sur une idée simple : structurer chaque cours avant d'en générer le texte.

Dans la première version, après l'étape 4 du programme journalier, chaque audio disposait seulement d'un thème et d'un descriptif de ce qu'il devait couvrir de manière globale. Désormais, avec cette nouvelle version, ce descriptif ne suffit plus : chacun des 7 audios d'une journée est organisé en un véritable déroulé, composé obligatoirement d'une introduction, de deux à quatre sous-parties (selon le thème abordé) et d'une conclusion.

Pour chaque bloc de ce déroulé (l'introduction, chaque sous-partie et la conclusion) le système précise des spécifications : les éléments à couvrir absolument et les éléments à éviter. On descend ainsi à un niveau de détail bien plus fin que dans la première version.

Vient ensuite l'étape clé. Pour chaque bloc, le système va piocher, parmi une bibliothèque de templates de slides couvrant de nombreuses situations pédagogiques, un enchaînement de slides adapté. Cet enchaînement n'est pas choisi au hasard. En effet, s'il est sélectionné, c'est parce qu'il correspond aux spécifications du cours et qu'il permet de faire avancer le déroulé pédagogique. On obtient ainsi, pour chaque sous-partie, une succession de slides porteuse d'un véritable fil conducteur.

Pour l'introduction et la conclusion, le procédé est encore plus encadré. En effet, puisque ces blocs sont scriptés, on ne pioche pas n'importe quelle slide dans les templates, mais des templates de slides déjà "scriptées" dans un ordre précis. S'il s'agit du premier cours de toute la formation, une slide d'accueil et de présentation du parcours ouvre la séance. S'il s'agit du premier cours d'une journée, c'est cette fois-ci une slide de programme du jour. Chaque introduction se termine par une slide annonçant les axes qui vont être abordés durant la journée ou durant le cours. La conclusion quant à elle est conçue de telle sorte à faire apparaître des slides qui récapitulent aux élèves les notions qui ont été vues.

*Figure 6 - Planification d'un chapitre: éléments à couvrir, à éviter et diapositives prévues.* *Figure 7- Association des modèles de diapositives à chaque sous-partie d'un chapitre.*

Une fois ce plan construit, une autre étape génère le texte. Contrairement à la première version, le LLM ne rédige plus librement cette fois-ci. Plutôt, il rédige le contenu des audios en suivant à la lettre cette structure qui prévoit déjà les supports visuels et l'enchaînement attendu. Le texte est donc produit slide par slide, en connaissant ce qu'il faut couvrir et ce qu'il faut éviter.

*Figure 8 - Deuxième version du pipeline, structurée par plan et intégrant les diapositives dès la planification.*

Cette organisation résout les quatre limites de la première version en même temps.

D'abord, le texte n'est plus trop libre : il suit un déroulé imposé, avec une introduction et une conclusion scriptées, ce qui garantit un fil pédagogique explicite (limite 1). Ensuite, comme le contenu est généré bloc par bloc, le budget de mots est éclaté entre l'introduction, chaque sous-partie et la conclusion. Chaque budget devient petit et donc facilement atteignable précisément par le modèle, ce qui rapproche la durée réelle de la durée visée (limite 3). Sur ces volumes réduits, les garde-fous deviennent eux aussi beaucoup plus efficaces : un LLM gère parfaitement un contexte aussi court, qu'il s'agisse de vérifier le budget de mots ou de corriger les erreurs et hallucinations évoquées précédemment (limite 2). Enfin, puisque le texte est rédigé à partir d'un enchaînement de slides, chaque passage de texte correspond nativement à une slide : l'association texte / support, auparavant fragile et reconstruite après coup, est désormais immédiate, et l'ensemble est globalement bien plus structuré (limite 4).

Le tableau suivant récapitule la manière dont chacune des quatre limites est adressée par cette seconde version.

| **Limite de la V1** | **Réponse apportée par la V2** | 
| **Limite 1 - Textes trop libres** | Le contenu de chacun des 7 audios suit désormais un plan (introduction, deux à quatre parties, conclusion), ce qui impose un fil pédagogique explicite au lieu d'un texte généré en bloc. L'introduction et la conclusion sont en outre scriptées. | 
| **Limite 2 - Garde-fous sur des volumes trop longs** | Le contenu étant découpé en blocs plus courts (parties et slides), les passes de micro-conformité analysent des textes plus petits et corrigent mieux. | 
| **Limite 3 - Calibrage imparfait** | Le budget de mots à atteindre est subdivisé. Chaque budget devient plus facilement atteignable de manière précise, ce qui rapproche la durée réelle de la durée visée. | 
| **Limite 4 - Intégration fragile des supports visuels** | Les templates de slides sont associés dès la phase de planification, et non plus après coup. Le texte est donc rédigé à partir d'une structure qui prévoit déjà les supports visuels, et l'enchaînement attendu. | 

*Figure 9 - Exemple d'une séquence de cours générée avec son script et ses diapositives.* *Figure 10 - Autre exemple de séquence de cours générée et des diapositives associées.*

Cette nouvelle organisation a donc permis de répondre à plusieurs problèmes en même temps : mieux structurer le contenu, mieux associer les slides au texte, faciliter la synchronisation avec l'audio et rendre les contrôles plus efficaces. La solution repose toujours sur la même logique de fond : subdiviser au maximum une tâche complexe pour rendre chaque étape plus simple, plus contrôlable et plus fiable.

### 4.2 Seconde fonction: répondre aux questions des apprenants

#### 4.2.1 Du cours diffusé à l'interaction pédagogique

Le pipeline présenté précédemment permet de reproduire une première fonction essentielle du professeur : produire et délivrer un cours. Le système génère un contenu structuré, le transforme en audio, l'accompagne de supports visuels et l'intègre dans un déroulé de journée avec transitions, pauses et temps de questions-réponses.

Cette première fonction donne une base solide : le professeur IA peut expliquer un cours, suivre une progression pédagogique et accompagner son discours avec des diapositives. Cependant, un professeur ne se limite pas à parler. Dans une formation réelle, il doit aussi répondre aux questions lorsqu'une notion n'est pas comprise, lorsqu'un exemple doit être précisé ou lorsqu'un apprenant souhaite revenir sur un point du cours.

C'est pour cette raison que le déroulé de la journée intègre des temps de questions-réponses. Pendant ces séquences, les apprenants posent leurs questions dans le chat, et le système doit pouvoir y répondre. La seconde fonction à reproduire est donc celle de l'interaction pédagogique.

#### 4.2.2 Le problème de contextualisation des réponses

Une première possibilité aurait été d'utiliser directement un LLM généraliste. Cette approche donnerait des réponses rapides et souvent cohérentes sur des notions générales. Mais elle présente une limite importante dans le contexte du projet : les réponses attendues ne doivent pas seulement être correctes en général, elles doivent être cohérentes avec le contenu réellement enseigné, le niveau de la formation, les supports diffusés et le vocabulaire utilisé pendant le cours.

Un modèle généraliste peut répondre en mobilisant ses connaissances générales, mais cette réponse peut être trop large, trop éloignée du cours, ou ajouter des informations non abordées, ce qui risque de créer de la confusion. Le problème n'est donc pas seulement de permettre au professeur IA de répondre, mais de lui permettre de répondre à partir du bon contexte : les réponses doivent être alignées avec les contenus de formation, et non uniquement avec la connaissance générale du modèle.

#### 4.2.3 Choix du RAG plutôt que le prompt engineering ou le fine-tuning

Plusieurs approches étaient envisageables : le prompt engineering, le fine-tuning et le Retrieval-Augmented Generation (RAG).

Le prompt engineering permet d'encadrer le comportement du modèle à l'aide de consignes. Il aurait été possible de lui demander de répondre comme un professeur, de rester concis et de s'appuyer sur le cours, en fournissant l'ensemble du contenu d'une journée dans le prompt. Mais cette approche poserait rapidement problème : le volume d'informations serait important, certaines informations seraient mal prises en compte, et le modèle risquerait de produire des réponses approximatives, incomplètes, voire contradictoires avec ce qui a été enseigné. Le prompt engineering oriente le comportement, mais ne garantit pas que les réponses soient réellement ancrées dans le contenu exact du cours.

Le fine-tuning aurait également pu être envisagé pour adapter un modèle à un style ou à un domaine. Cette méthode peut par exemple être utile sur un domaine de niche, comme les sports équestres olympiques, où les LLM sont trop généralistes pour connaître toutes les spécificités. Mais le besoin de la plateforme était différent : les formations portent sur des titres professionnels relativement généralistes, et les contenus sont eux-mêmes produits avec l'aide de LLM. Le problème n'était donc pas de rendre le modèle expert d'un domaine rare, mais de lui permettre de répondre à partir du contenu précis du cours diffusé.

Le fine-tuning amène également une difficulté opérationnelle. En effet, il faut constituer un jeu de données et adapter le modèle. Même avec des méthodes légères comme LoRA ou QLORA, cela reste lourd à maintenir, surtout dans une logique purement commerciale. De plus, les contenus changent d'un titre professionnel à l'autre, voire d'un cours à l'autre. Utiliser le fine-tuning impliquerait donc de réentraîner un modèle pour chaque formation, ce qui serait peu réaliste. Enfin, le fine-tuning ne garantit pas que la réponse soit fondée sur ce qui a réellement été dit dans le cours.

La solution résidait donc dans une approche de type RAG. Son principe : rechercher, au moment où une question est posée, les passages les plus pertinents dans les contenus de formation, puis les fournir au modèle pour qu'il génère sa réponse. Le modèle ne répond plus uniquement à partir de sa connaissance générale, mais à partir d'un contexte extrait des documents réellement utilisés dans la formation.

#### 4.2.4 Fonctionnement d'un RAG classique

Dans sa forme classique, un RAG repose sur trois grandes étapes : l'encodage des documents, la recherche des passages pertinents, puis la génération de la réponse.

Dans un premier temps, les fichiers de cours, au format PDF, sont récupérés puis découpés en segments de texte appelés chunks. Ce découpage permet de travailler sur des portions plus petites qu'un document complet, ce qui facilite la recherche d'informations précises. Dans ce projet, le modèle d'embedding utilisé est `text-embedding-3-small`, proposé par OpenAI. L'embedding obtenu constitue une représentation mathématique du contenu, permettant de comparer les passages non pas à partir des mots exacts, mais de leur proximité sémantique. Les vecteurs générés sont stockés dans une base vectorielle, qui permet de retrouver rapidement les passages les plus proches d'une question via une mesure de similarité, généralement la similarité cosinus.

*Figure 11-Indexation du RAG: découpage des cours en chunks, encodage en embeddings et stockage dans la base vectorielle.*

Lorsqu'un utilisateur pose une question, celle-ci est elle aussi transformée en vecteur. Ce vecteur de requête est ensuite comparé aux vecteurs des chunks stockés dans la base vectorielle.

*Figure 12-Recherche vectorielle: la question est encodée puis comparée aux chunks de la base.*

Les chunks dont les embeddings sont les plus proches sont sélectionnés, puis injectés dans un prompt envoyé au LLM (ici GPT-4) avec la question. Le prompt précise que l'agent doit se comporter comme un formateur clair et bienveillant, répondre de manière pédagogique et s'appuyer uniquement sur les documents disponibles. La réponse est enfin transmise à l'utilisateur.

*Figure 13-Architecture RAG vectorielle complète, de la question de l'apprenant à la génération de la réponse.*

#### 4.2.5 D'un RAG vectoriel vers une recherche hybride (Hybrid Search + RRF)

L'architecture décrite ci-dessus correspond à une version simple du RAG, fondée principalement sur une base vectorielle. Elle est utile lorsque l'apprenant formule une question avec des mots différents de ceux du cours. Mais elle présente une limite dans un contexte pédagogique, certaines notions doivent être retrouvées de manière très précise. Si un apprenti pose une question sur le CRM, le RGPD, ou le recouvrement amiable, il est important de retrouver les passages où ces termes apparaissent explicitement.

Pour répondre à cette double exigence, j'ai fait le choix d'une architecture RAG fondée sur l'hybrid search et le RRF, afin de ne pas dépendre d'une seule méthode de recherche mais de combiner recherche textuelle et recherche vectorielle. L'architecture ne repose donc pas sur une simple base vectorielle, mais sur un index documentaire hybride conservant à la fois le texte des chunks, leurs embeddings et leurs métadonnées.

*Figure 14-Index documentaire hybride conservant à la fois le texte et les embeddings des chunks.*

La première recherche est textuelle. Elle s'appuie sur un score de type BM25. BM25 repose sur deux idées. La première est la fréquence du terme (nommée TF) : un chunk mentionnant plusieurs fois le mot « CRM » sera jugé plus pertinent qu'un chunk ne le mentionnant qu'une fois. La seconde est la rareté du terme dans le corpus (nommée IDF) : un mot présent dans presque tous les chunks (comme "formation", ou "apprenti") apporte peu d'informations pour distinguer un passage d'un autre, tandis qu'un terme spécifique (« RGPD-MIN-12 », « recouvrement amiable ») est bien plus utile pour retrouver le bon passage. Cette recherche est donc par exemple particulièrement efficace pour les termes exacts, ou encore les acronymes.

La seconde recherche est vectorielle. Elle permet comme évoqué précédemment de retrouver les passages qui ont un sens proche des mots évoqués dans la question.

Lorsqu'un apprenti pose une question, le système effectue les deux recherches en parallèle. On obtient ainsi deux listes de n résultats. Il faut ensuite les fusionner en une seule liste : c'est le rôle du Reciprocal Rank Fusion (RRF), qui favorise les chunks bien classés dans les deux recherches.

*Figure 15-Mécanisme de la recherche hybride et fusion des résultats par Reciprocal Rank Fusion (RRF).*

Par exemple, à la question « Pourquoi faut-il qualifier le CRM après un appel? », la recherche textuelle fait remonter les passages contenant « CRM » et « qualification », tandis que la recherche vectorielle retrouve des passages parlant de traçabilité ou de suivi client, même formulés différemment. Le RRF fusionne ces résultats pour sélectionner les chunks les plus pertinents. Cette approche combine la précision des mots-clés avec la souplesse de la recherche sémantique, et augmente les probabilités que les bons chunks soient transmis au LLM.

*Figure 16-Architecture RAG hybride complète: recherche lexicale et vectorielle, fusion par RRF puis génération.*

#### 4.2.6 Évaluation de la récupération documentaire

Afin de vérifier l'intérêt de cette architecture hybride, une évaluation a été réalisée. L'objectif est d'évaluer la capacité de notre RAG à récupérer les bons passages. Au sein d'un RAG, c'est cette étape qui est essentielle : si les bons chunks ne sont pas récupérés, le modèle ne dispose pas du bon contexte et risque de produire une réponse imprécise ou mal ancrée.

Le principe du test : pour chaque question, le passage du corpus contenant la bonne réponse a d'abord été repéré manuellement. Le système était ensuite interrogé avec trois configurations (recherche textuelle BM25, recherche vectorielle et recherche hybride) afin de vérifier si chaque méthode faisait remonter ce bon passage parmi les premiers résultats.

Trois métriques ont été utilisées. Le `Recall@K` mesure si le bon chunk apparaît dans les K premiers résultats. Nous nous intéressons principalement à K=3, car un RAG transmet généralement plusieurs passages au LLM, et non un seul. `Recall@K` = (nombre de chunks pertinents retrouvés dans les K premiers) / (nombre total de chunks pertinents attendus)

La `Precision@K` mesure la proportion de chunks pertinents parmi les K résultats retournés. `Precision@K` = (nombre de chunks pertinents dans les K premiers) / K

Enfin, le `MRR` mesure le rang du premier résultat pertinent : plus le bon chunk apparaît haut dans la liste, plus le score est élevé. `MRR` = 1 / (rang du premier résultat pertinent)

L'analyse a été menée sur deux grandes familles de questions.

**Première famille : les questions avec une formulation différente de celle présente dans le corpus** La question ne reprend pas forcément les mots exacts du chunk attendu. Par exemple : « Que faire pour aider une personne qui comprend difficilement les consignes ? » Le chunk attendu explique qu'il faut adapter son discours (phrases courtes, rythme ralenti, vérification de chaque étape) sans utiliser les mêmes mots. Les résultats à K=3 sont les suivants :

| **Configuration** | **Recall@3** | **Precision@3** | **MRR** | 
| **BM25** | 0,625 | 0,208 | 0,354 | 
| **Recherche vectorielle** | 0,875 | 0,292 | 0,625 | 
| **Recherche hybride** | 0,875 | 0,292 | 0,562 | 

Ces résultats montrent que BM25 est moins performant sur les questions qui ont une formulation différente du passage dans le corpus qui permet d'y répondre. Il s'appuie surtout sur les mots de la question et peut être attiré par des passages contenant certains de ces mots sans répondre à l'intention. La recherche vectorielle quant à elle retrouve mieux le passage attendu et la recherche hybride conserve cet avantage puisqu'elle intègre le signal vectoriel.

**Seconde famille : les questions avec termes exacts, codes métier ou métadonnées.** Par exemple: « Quelle action correspond à META-BQ9-QUALITE ? ». Ici, l'information importante est un identifiant. Les résultats à K=3 sont les suivants :

| **Configuration** | **Recall@3** | **Precision@3** | **MRR** | 
| **BM25** | 1,000 | 0,333 | 1,000 | 
| **Recherche vectorielle** | 0,667 | 0,222 | 0,444 | 
| **Recherche hybride** | 1,000 | 0,333 | 0,833 | 

Ces résultats montrent que la recherche vectorielle seule est moins adaptée aux identifiants exacts : un code comme META-BQ9-QUALITE n'a pas réellement de sens sémantique et doit surtout être retrouvé comme une chaîne de caractères précise, ce que BM25 gère mieux.

On observe ainsi avec ces deux tests la complémentarité des deux approches. L'intérêt de l'hybrid search est de combiner ces deux forces.

## 5. Discussion et conclusion

La solution développée a été conçue dans le contexte de formations professionnelles préparant à des certifications reconnues par l'État. Toutefois, son champ d'application est plus large. Elle pourrait être adaptée à tout autre type de formations.

### 5.1 Limites et pistes d'évolution

À ce stade, la validation de la solution est avant tout empirique. L'approche a été mise au point de manière itérative : de nombreuses générations de formations ont été lancées, et le pipeline a toujours produit de bons résultats.

De son côté, l'architecture RAG retenue permet aussi de fournir d'excellentes réponses aux questions lors des tests. En revanche, la solution venant tout juste d'être finalisée, elle n'a pas encore été déployée auprès de promotions réelles (elle le sera sur les prochaines formations). Je ne dispose donc pas encore de retours d'apprenants permettant d'évaluer la qualité pédagogique réellement perçue.

Plusieurs améliorations sont par ailleurs déjà identifiées, et chacune ouvre une piste d'évolution concrète. Aujourd'hui, les échanges avec les apprenants se limitent à des questions posées à l'écrit pendant les temps de questions-réponses. Il serait possible, de faire répondre le professeur IA à l'oral et en direct aux questions posées dans le chat, afin de se rapprocher davantage d'une formation animée par un humain.

De même, l'architecture de réponse pourrait évoluer vers un RAG conversationnel, capable de conserver l'historique des échanges, afin de tenir compte des questions précédentes et de rendre le dialogue plus naturel. Enfin, la solution ne propose pas encore de suivi individualisé ni d'exercices ou de quiz permettant d'évaluer les acquis : ce sont des pistes d'enrichissement naturelles, par exemple en accompagnant les apprenants qui souhaitent réviser et se préparer au titre professionnel les jours sans formation.

À une échelle plus large, le projet ouvre une perspective dépassant le seul usage interne. Le fondateur souhaite faire évoluer la solution vers une plateforme commercialisée sous forme de SaaS, qui permettrait à d'autres centres de formation de créer leur propre professeur IA et leurs propres formations alimentées par l'intelligence artificielle. Cette phase n'a pas encore débuté, mais l'entreprise prévoit de l'engager prochainement. Elle constitue l'évolution la plus ambitieuse ouverte par ce travail, en faisant passer la solution d'un outil interne à un produit destiné au marché.

### 5.2 Apports professionnels et montée en compétences

Sur le plan de l'entreprise, la solution apporte un bénéfice opérationnel direct. Auparavant, la production des formations mobilisait plusieurs heures de travail, notamment de la part de la chargée des ressources humaines, et le dirigeant devait lui-même parfois prendre en charge cette tâche. En automatisant la génération des contenus et leur mise en forme, la solution libère ce temps et supprime la dépendance aux interventions humaines, qu'il s'agisse de la rédaction des cours ou de l'enregistrement des voix off. Elle réduit ainsi les risques liés aux indisponibilités et au turnover, tout en rendant l'activité de formation plus rentable, et ouvre le champ des possibles vers une montée en charge et la commercialisation évoquée précédemment.

Sur le plan personnel, ce projet a constitué une véritable montée en compétences. La principale leçon que j'en retire est la capacité à décomposer un problème complexe jusqu'à le rendre réalisable : c'est cette démarche qui a structuré l'ensemble du travail, qu'il s'agisse du pipeline de génération construit étape par étape, ou du choix d'une architecture de réponse adaptée au besoin. Sur le plan technique, je connaissais déjà le principe du RAG, mais ce projet m'a permis d'apprendre à l'améliorer concrètement, à travers la recherche hybride et le RRF.

Ce projet m'a enfin permis de développer une réelle autonomie de conception. En tant que seul concepteur et développeur de la plateforme, j'ai pris en charge l'architecture, les choix d'implémentation et l'étude de leur faisabilité, tout en adoptant une posture de force de proposition. Le dialogue régulier avec le dirigeant, à qui je présentais mes choix pour validation, m'a également appris à articuler une vision technique avec des objectifs d'entreprise. C'est cette combinaison de compétences techniques et de prise de recul qui constitue, à mes yeux, le véritable apport de ce travail.

## Bibliographie

\[1\] Shubham Sarkar. *Hybrid Search in RAG: Concept of Weighted Reciprocal Rank Fusion (RRF) - Part 1*. Medium, 2024. Article présentant le fonctionnement de la recherche hybride dans les architectures RAG et le mécanisme de fusion des résultats par Reciprocal Rank Fusion (RRF). https://medium.com/@shubhamsarkar996/hybrid-search-in-rag-concept-of-weighted-reciprocal-rank-fusion-rrf-part-1-ae570d9c1879

\[2\] Red Hat. *LoRA vs QLORA: quelles différences ?*. Red Hat. Article expliquant les méthodes de fine-tuning LoRA et QLoRA, leurs principes de fonctionnement et leurs compromis en termes de performance et de consommation mémoire. https://www.redhat.com/fr/topics/ai/lora-vs-qlora

\[3\] IBM Technology. *What is Retrieval-Augmented Generation (RAG)?*. Vidéos de vulgarisation présentant le fonctionnement général des architectures RAG, leurs avantages et leurs principaux cas d'usage. https://youtu.be/63B-3rqRFbQ?si=J3Wzlb_9sxjPyPee

\[4\] Juwa. *Les métriques d'évaluation d'un système RAG*. Juwa. Article décrivant les principales métriques utilisées pour évaluer les performances d'un système RAG, notamment la pertinence de la récupération documentaire et la qualité des réponses générées. https://juwa.co/blog/guides-methodes-ia/metriques-evaluation-rag/

\[5\] Wikipédia. *Fenêtre de contexte*. Wikipédia, consulté en 2026. Article présentant la notion de fenêtre de contexte utilisée par les modèles de langage et son impact sur le traitement des informations fournies au modèle. https://fr.wikipedia.org/wiki/Fen%C3%AAtre_de_contexte

## Remerciements

Je tiens tout d'abord à remercier l'ensemble de l'équipe d'Audits Énergies pour son accueil, sa confiance et les conditions de travail qui m'ont permis de mener à bien ce projet tout au long de mon alternance.

J'adresse un remerciement particulier à M. Mehdi Rousselle, mon tuteur entreprise, pour sa bienveillance, son accompagnement, sa disponibilité ainsi que la confiance qu'il m'a accordée dans la conception et le développement de cette plateforme.

Je remercie également M. Valentin Guemache, l'autre dirigeant de l'entreprise. Même s'il n'est pas intervenu directement dans la réalisation de ce projet, sa bienveillance et sa sympathie ont largement contribué à rendre cette expérience professionnelle particulièrement agréable.

Je souhaite également remercier M. Moulay Ahansal, mon tuteur pédagogique, pour son accompagnement durant cette dernière année à l'EFREI. Dès le début de l'année, il m'a transmis plusieurs conseils qui m'ont accompagné tout au long de mon alternance et de la réalisation de ce mémoire.

Enfin, je souhaite remercier l'EFREI pour ces années de formation, riches en apprentissages et en expériences. Ce mémoire vient conclure un parcours qui m'a permis de développer mes compétences techniques et de grandir tant sur le plan professionnel que personnel.