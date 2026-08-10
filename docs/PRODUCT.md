# Product

## Register

product

## Users

**Admins / formateurs (P1)** — opèrent le parc multi-plateforme depuis HR Dashboard. Pilotent la pipeline de génération formation (REAC → KB → contenu → audio TTS), gèrent les promos, configurent les heures de cours, lockent/délockent l'accès aux audios, exportent les logs RH. Utilisent l'outil quotidiennement, connaissent les concepts métier (RNCP, REAC, modules, promo). **Persona prioritaire en cas de conflit de design** : si un choix UX avantage l'apprenant au détriment de l'admin, on choisit l'admin.

**Apprenants (P2 / P3 / P4)** — suivent un cours audio synchronisé à heure fixe (playlist horodatée + Q&A IA) sur leur plateforme de promo. Préparent un titre professionnel RNCP. Public adulte en formation continue (pas étudiants). Contexte d'usage : connexion à 9h pile pour rejoindre la classe virtuelle, écoute du cours en passive listening + interaction Q&A. Pas en présentiel, pas en podcast asynchrone — classe virtuelle synchrone simulée.

Voir `memoire/01-architecture/un-rncp-un-module-durable.md` et `wiki/Intelligence/un-rncp-un-module-durable.md` (vault) pour le principe fondateur : 1 RNCP = 1 module audio durable, réutilisé pour toutes les promos. Les admins produisent une fois, les apprenants consomment N fois.

## Product Purpose

Plateforme de formation en ligne synchrone pour titres professionnels RNCP. Combine :

1. **Côté apprenant** : expérience de classe virtuelle simulée (playlist audio horodatée + Q&A IA contextuel) qui reproduit la rigueur d'un cours synchrone à heure fixe.
2. **Côté admin** : pipeline complète de génération de contenu pédagogique (REAC → knowledge base → contenu rédigé → audio TTS Fish Audio S2-Pro / gTTS), couplée à un tableau de bord HR pour piloter les promos en multi-tenant (P1–P4).

Succès = un module audio complet et durable produit par la pipeline DeepSeek, puis réutilisé tel quel pour toutes les promos du même RNCP (économie d'échelle native, coûts DeepSeek + TTS amortis). L'apprenant doit ressentir la rigueur d'un titre certifiant ; l'admin doit pouvoir opérer le parc sans drama.

## Brand Personality

**Rigoureuse · institutionnelle · sobre.**

- **Voix** : posée, claire, factuelle. Pas de tournures commerciales ("Boostez votre carrière !"). Pas de tournures motivationnelles ("Tu peux le faire !"). Pas d'humour. Le ton d'un préparateur de concours sérieux ou d'un formateur agréé qui sait son métier.
- **Posture émotionnelle visée — apprenant** : sérieux institutionnel. Quand l'apprenant ouvre `/video` à 9h pile, il doit ressentir le cadre RNCP officiel, la crédibilité du titre, la posture pro. Pas chaleureux complice, pas énergique coaching, pas effacé focus-mode. Sérieux.
- **Posture émotionnelle visée — admin** : calme professionnel. Quand l'admin ouvre `/hr-dashboard`, il doit ressentir le minimalisme Linear/Stripe : épuré, sobre, rassurant. Pas cockpit mission-control, pas power-user sec, pas identité forte. Calme.
- **Trait dominant** : crédibilité institutionnelle. Le Socrate forme à des titres reconnus par l'État — le design doit transpirer ce cadre, pas le diluer dans du SaaS générique ou de l'edtech ludique.

## Anti-references

**Anti-référence principale (sélection explicite) — Edtech "playful"** :

- **Duolingo, Memrise, Brilliant, Khan Academy Kids.** Gamification, mascots cartoon, couleurs primaires saturées, animations célébratoires, badges en confettis, "streaks", "XP", "level up". Tout ce qui dit "formation ludique" est à proscrire absolument. Le Socrate prépare un titre RNCP certifiant, pas un quiz du dimanche.
- Implication concrète : pas de Lottie célébration de fin de module, pas de jaune/orange/rouge primaires saturés sur les CTA, pas de mascot Le Socrate, pas de "Bravo ! 🎉", pas de progress bar avec petit personnage qui marche.

**Anti-références implicites (héritées des design laws partagés et de l'épisode HR Dashboard)** :

- **Pattern AI slop générique** : carré violet rounded-xl + Material Icon abstrait (`hub`, `auto_awesome`, `bolt`) en logo-mark. Cf. l'épisode du logo HR Dashboard refusé en cours de session. Si je propose ça à nouveau, c'est un échec.
- **Hero-metric template SaaS** : grand chiffre + petit label + supporting stats + accent gradient. Cliché.
- **Identical card grids** : 4 cartes même taille avec icône + titre + texte, alignées en grille. Le réflexe AI mockup. Toujours un signe de paresse design.
- **Gradient text** (`background-clip: text` sur titre) : décoratif sans signification.
- **Glassmorphism par défaut** (blurs + glass cards) : utilisable rare et pour raison précise, jamais comme remplissage.

## Design Principles

1. **L'institution avant l'expérience.** Le Socrate prépare des titres RNCP — la crédibilité institutionnelle prime sur le plaisir d'usage. Quand on choisit entre "officiel sérieux" et "agréable et fun", on choisit officiel. Le design doit faire dire à l'apprenant "c'est une vraie école certifiante", pas "c'est sympa cette appli".

2. **L'opérateur avant l'apprenant en cas de conflit.** Les admins/formateurs sont les utilisateurs durs : ils opèrent quotidiennement, connaissent les concepts métier, pilotent un parc multi-plateforme. Quand un design avantage un persona au détriment de l'autre, **l'admin gagne par défaut**. La latitude pour soigner l'apprenant existe quand la décision n'a pas de coût admin.

3. **Calme sans froideur académique.** Double référence : Coursera / edX / MIT OCW (institutionnel légitime, crédibilité titre) ET Linear / Stripe / Notion (minimalisme calme product). Le mariage des deux = sobriété crédible. À éviter : Moodle gris déprimant (institutionnel mort) ET startup-coloré (calme cassé par fioritures).

4. **Un RNCP, un module durable, un design durable.** Le contenu est produit une fois par RNCP et réutilisé pour toutes les promos (cf. `memoire/01-architecture/un-rncp-un-module-durable.md`). Le design doit suivre la même logique : éviter les choix "tendance 2026" qui dateront en 2028. Privilégier le sobre éprouvé qui ne demande pas de refonte chaque saison.

5. **Anti-Duolingo strict.** Aucune gamification, pas de mascots, pas de confettis, pas de couleurs primaires saturées, pas d'animations célébratoires d'achievement, pas de "streaks". Si la formation devait être ludique, le marché aurait choisi Duolingo et pas Le Socrate. Le sérieux est un produit, pas un défaut à compenser.

## Accessibility & Inclusion

Pas d'audit WCAG complet en priorité immédiate (décision explicite). Sens commun appliqué par défaut :

- Contraste lisible (≥ 4.5:1 sur le texte courant, on n'évite pas spécifiquement les contrastes faibles décoratifs).
- Focus visible préservé (ne pas masquer les outlines navigateur sans alternative).
- Hiérarchie sémantique HTML correcte (pas de div soup).
- Si un besoin spécifique remonte (ex. apprenant avec lecteur d'écran, daltonien, mobilité réduite), on traite à ce moment-là.

À revisiter en passe d'audit dédiée si la cible apprenant s'élargit ou si une exigence légale tombe (formation publique financée → CPF / Qualiopi peut imposer RGAA AA).
