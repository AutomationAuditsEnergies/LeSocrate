# Inscriptions — المدرسة القرآنية محمد الشريف ڨاهر

Refonte du site https://apricot-stevena-33.tiiny.site/ :

1. Le parent remplit le formulaire (`index.html`), avec photo facultative.
2. Un **Google Apps Script** gratuit (`apps-script/Code.gs`) reçoit l'inscription et :
   - ajoute l'élève dans un **Google Sheet en ligne** (une ligne par élève, + liens PDF/photo) ;
   - remplit le **modèle de استمارة التسجيل** (`modele-inscription.docx`, copie de votre PDF) et le convertit en **PDF** ;
   - envoie le PDF par e-mail à **abdellaouiyoucef04@gmail.com** (et une copie au parent s'il a mis son e-mail) ;
   - range tous les PDF dans un dossier Google Drive « Inscriptions PDF ».

Tout tourne sur le compte Google **abdellaouiyoucef04@gmail.com** : pas de serveur, pas d'abonnement.

```
index.html (formulaire)  ──POST──►  Apps Script  ──►  Google Sheet  (liste des élèves)
                                         ├──────►  Google Docs modèle → PDF  (Drive)
                                         └──────►  Gmail : PDF en pièce jointe
```

## Fichiers

| Fichier | Rôle |
|---|---|
| `index.html` | Le site (même design que l'actuel) |
| `logo.png`, `regulations.jpg` | Logo de l'école et image du النظام الداخلي |
| `modele-inscription.docx` | Modèle de la fiche, avec des balises `{{NOM_ELEVE}}`, `{{PHOTO}}`… |
| `apps-script/Code.gs` | Le code à coller dans Google Apps Script |
| `outils/generer_modele.py` | Régénère le modèle `.docx` si besoin |

## Installation (≈ 10 minutes, connecté à abdellaouiyoucef04@gmail.com)

### 1. Le modèle de fiche (Google Docs)
1. Ouvrir https://drive.google.com → **Nouveau → Importer un fichier** → `modele-inscription.docx`.
2. Clic droit sur le fichier → **Ouvrir avec → Google Docs** (cela crée une version Google Docs).
3. Vous pouvez retoucher la mise en page librement, **en gardant les balises `{{...}}`** intactes.
4. Copier l'**ID** dans l'URL : `https://docs.google.com/document/d/`**`CET_ID_ICI`**`/edit`.

> Astuce : vous pouvez aussi utiliser votre propre fiche Word d'origine : ouvrez-la dans Google Docs
> et remplacez les pointillés par les balises : `{{DATE_INSCRIPTION}}`, `{{NUMERO}}`, `{{NOM_ELEVE}}`,
> `{{DATE_NAISSANCE}}`, `{{ADRESSE}}`, `{{NIVEAU}}`, `{{TEL_ELEVE}}`, `{{CASE_OUI}}`, `{{CASE_NON}}`,
> `{{SANTE_DETAILS}}`, `{{NOM_TUTEUR}}`, `{{CNI_TUTEUR}}`, `{{TEL_TUTEUR}}`, `{{EMAIL}}`, `{{ACCORD}}`,
> `{{HORODATAGE}}`, et `{{PHOTO}}` dans le cadre « صورة شمسية ».

### 2. Le Google Sheet
1. Ouvrir https://sheets.new → nommer le fichier par ex. **« تسجيلات الطلبة 2026 »**.
2. Menu **Extensions → Apps Script**.

### 3. Le script
1. Dans l'éditeur Apps Script, effacer le contenu de `Code.gs` et coller tout `apps-script/Code.gs`.
2. En haut du fichier, remplacer `COLLER_ICI_ID_DU_MODELE` par l'ID copié à l'étape 1.
3. Enregistrer (icône disquette).

### 4. Autoriser et tester
1. Dans la liste des fonctions (en haut), choisir **`installer`** → **Exécuter**.
   Google demande des autorisations (Sheets, Drive, Docs, Gmail) → **Autoriser**.
   Si « Google n'a pas validé cette application » : **Paramètres avancés → Accéder au projet (non sécurisé)** — c'est normal, c'est votre propre script.
2. Choisir **`testerInscription`** → **Exécuter** : vous devez recevoir un e-mail avec le PDF, et voir une ligne « تجربة » dans l'onglet **Inscriptions** du Sheet. Supprimez ensuite cette ligne de test.

### 5. Mettre le script en ligne
1. **Déployer → Nouveau déploiement** → roue dentée → **Application Web**.
2. *Exécuter en tant que* : **Moi** · *Qui a accès* : **Tout le monde**.
3. **Déployer** → copier l'**URL de l'application Web** (se termine par `/exec`).
4. Dans `index.html`, remplacer `COLLER_ICI_URL_APPS_SCRIPT` par cette URL.

> Si vous modifiez `Code.gs` plus tard : **Déployer → Gérer les déploiements → ✏️ → Version : Nouvelle version**,
> pour garder la même URL.

### 6. Publier le site
Envoyer les 3 fichiers **`index.html`, `logo.png`, `regulations.jpg`** (dans un même dossier / zip) sur
tiiny.host comme avant — ou gratuitement sur Netlify Drop (https://app.netlify.com/drop) ou GitHub Pages.

## Bon à savoir
- **Quota Gmail** : un compte Gmail gratuit peut envoyer ~100 e-mails/jour via Apps Script
  (avec la copie au parent, ≈ 50 inscriptions/jour). Pour désactiver la copie au parent :
  `ENVOYER_COPIE_AU_PARENT: false`.
- **Numéro d'inscription** automatique : `2026-0001`, `2026-0002`…
- Les colonnes du Sheet sont en texte : le `0` des téléphones est conservé.
- Le Sheet peut être partagé (lecture seule) avec les enseignants via le bouton **Partager**.
- Données personnelles d'enfants : ne partagez le Sheet et le dossier Drive qu'avec les responsables de l'école.
