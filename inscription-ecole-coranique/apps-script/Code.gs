/**
 * المدرسة القرآنية محمد الشريف ڨاهر — backend des inscriptions (Google Apps Script)
 *
 * À chaque inscription envoyée par index.html :
 *   1. ajoute une ligne dans le Google Sheet (onglet "Inscriptions")
 *   2. copie le modèle Google Docs, remplace les {{BALISES}}, insère la photo
 *   3. convertit en PDF et le range dans le dossier Drive "Inscriptions PDF"
 *   4. envoie le PDF par e-mail à l'école (et une copie au parent s'il a donné son e-mail)
 *
 * Installation : voir README.md (étapes 1 à 5).
 */

const CONFIG = {
  EMAIL_ECOLE: 'abdellaouiyoucef04@gmail.com',
  // ID du Google Docs modèle : la partie entre /d/ et /edit dans son URL
  TEMPLATE_DOC_ID: 'COLLER_ICI_ID_DU_MODELE',
  NOM_ONGLET: 'Inscriptions',
  NOM_DOSSIER_PDF: 'Inscriptions PDF - المدرسة القرآنية',
  ENVOYER_COPIE_AU_PARENT: true,
  FUSEAU: 'Africa/Algiers',
  NOM_ECOLE: 'المدرسة القرآنية محمد الشريف ڨاهر',
};

// Colonnes du Google Sheet (ordre = ordre d'affichage)
const COLONNES = [
  ['numero', 'رقم التسجيل'],
  ['horodatage', 'تاريخ ووقت الإرسال'],
  ['dateInscription', 'تاريخ التسجيل'],
  ['nomEleve', 'اسم ولقب الطالب'],
  ['dateNaissance', 'تاريخ الميلاد'],
  ['niveau', 'المستوى التعليمي'],
  ['adresse', 'العنوان'],
  ['telEleve', 'هاتف الطالب'],
  ['sante', 'مشكل صحي'],
  ['santeDetails', 'تفاصيل المشكل الصحي'],
  ['nomTuteur', 'اسم ولي الأمر'],
  ['cniTuteur', 'رقم بطاقة التعريف'],
  ['telTuteur', 'هاتف الولي'],
  ['email', 'البريد الإلكتروني'],
  ['accord', 'الموافقة على النظام الداخلي'],
  ['lienPdf', 'الاستمارة PDF'],
  ['lienPhoto', 'الصورة'],
];

const OBLIGATOIRES = ['nomEleve', 'dateNaissance', 'niveau', 'adresse', 'nomTuteur', 'cniTuteur', 'telTuteur'];

/* ------------------------------------------------------------------ */
/* Point d'entrée web                                                  */
/* ------------------------------------------------------------------ */

function doGet() {
  return json_({ ok: true, message: 'Service d\'inscription actif.' });
}

function doPost(e) {
  const lock = LockService.getScriptLock();
  lock.waitLock(30000); // évite 2 inscriptions avec le même numéro
  try {
    const d = JSON.parse(e.postData.contents);
    if (d.botcheck) return json_({ ok: true }); // robot (champ caché rempli)
    return json_(enregistrer_(d));
  } catch (err) {
    console.error(err);
    return json_({ ok: false, error: String(err && err.message ? err.message : err) });
  } finally {
    lock.releaseLock();
  }
}

/* ------------------------------------------------------------------ */
/* Traitement d'une inscription                                        */
/* ------------------------------------------------------------------ */

function enregistrer_(d) {
  OBLIGATOIRES.forEach(function (k) {
    if (!String(d[k] || '').trim()) throw new Error('Champ obligatoire manquant : ' + k);
  });
  if (d.accord !== true && d.accord !== 'true') throw new Error('Le règlement intérieur doit être accepté.');

  const sheet = onglet_();
  const dossier = dossier_();
  const maintenant = new Date();

  const v = {};
  COLONNES.forEach(function (c) { v[c[0]] = nettoyer_(d[c[0]]); });
  v.numero = prochainNumero_(maintenant);
  v.horodatage = Utilities.formatDate(maintenant, CONFIG.FUSEAU, 'yyyy-MM-dd HH:mm:ss');
  v.dateInscription = v.dateInscription || Utilities.formatDate(maintenant, CONFIG.FUSEAU, 'yyyy-MM-dd');
  v.sante = d.sante === 'نعم' ? 'نعم' : 'لا';
  v.santeDetails = v.sante === 'نعم' ? v.santeDetails : '';
  v.accord = 'نعم، أوافق';

  // Photo (facultative) envoyée en base64 par le formulaire
  let photo = null;
  if (d.photo && d.photo.data) {
    photo = Utilities.newBlob(Utilities.base64Decode(d.photo.data), d.photo.type || 'image/jpeg',
                              v.numero + ' - ' + v.nomEleve + ' - photo.jpg');
    v.lienPhoto = dossier.createFile(photo).getUrl();
  }

  const pdf = genererPdf_(v, photo);
  const fichierPdf = dossier.createFile(pdf);
  v.lienPdf = fichierPdf.getUrl();

  sheet.appendRow(COLONNES.map(function (c) { return pourSheet_(v[c[0]]); }));

  envoyerEmails_(v, pdf);
  return { ok: true, numero: v.numero };
}

function genererPdf_(v, photo) {
  const nom = 'استمارة تسجيل ' + v.numero + ' - ' + v.nomEleve;
  const copie = DriveApp.getFileById(CONFIG.TEMPLATE_DOC_ID).makeCopy(nom);
  try {
    const doc = DocumentApp.openById(copie.getId());
    const body = doc.getBody();

    const balises = {
      NUMERO: v.numero,
      DATE_INSCRIPTION: v.dateInscription,
      NOM_ELEVE: v.nomEleve,
      DATE_NAISSANCE: v.dateNaissance,
      ADRESSE: v.adresse,
      NIVEAU: v.niveau,
      TEL_ELEVE: v.telEleve || '—',
      CASE_OUI: v.sante === 'نعم' ? '☒' : '☐',
      CASE_NON: v.sante === 'نعم' ? '☐' : '☒',
      SANTE_DETAILS: v.santeDetails || '—',
      NOM_TUTEUR: v.nomTuteur,
      CNI_TUTEUR: v.cniTuteur,
      TEL_TUTEUR: v.telTuteur,
      EMAIL: v.email || '—',
      ACCORD: v.accord,
      HORODATAGE: v.horodatage,
    };
    Object.keys(balises).forEach(function (k) {
      body.replaceText('\\{\\{' + k + '\\}\\}', String(balises[k]).replace(/\$/g, ''));
    });

    // Cadre photo : image si fournie, sinon le texte « صورة شمسية »
    const trouve = body.findText('\\{\\{PHOTO\\}\\}');
    if (trouve) {
      const texte = trouve.getElement().asText();
      if (photo) {
        const para = texte.getParent().asParagraph();
        texte.setText('');
        const img = para.appendInlineImage(photo);
        const largeur = 95; // ≈ 3,4 cm
        img.setHeight(Math.round(img.getHeight() * largeur / img.getWidth())).setWidth(largeur);
      } else {
        texte.setText('صورة شمسية');
      }
    }

    doc.saveAndClose();
    return copie.getAs('application/pdf').setName(nom + '.pdf');
  } finally {
    copie.setTrashed(true); // on ne garde que le PDF
  }
}

function envoyerEmails_(v, pdf) {
  const lignes = COLONNES
    .filter(function (c) { return c[0] !== 'lienPdf' && c[0] !== 'lienPhoto' && v[c[0]]; })
    .map(function (c) {
      return '<tr><td style="padding:4px 10px;color:#555">' + c[1] + '</td>' +
             '<td style="padding:4px 10px;font-weight:bold">' + echapper_(v[c[0]]) + '</td></tr>';
    }).join('');

  MailApp.sendEmail({
    to: CONFIG.EMAIL_ECOLE,
    subject: 'تسجيل جديد ' + v.numero + ' — ' + v.nomEleve,
    htmlBody: '<div dir="rtl" style="font-family:Tahoma,Arial">' +
              '<h2 style="color:#0d5c3d">تسجيل جديد — ' + CONFIG.NOM_ECOLE + '</h2>' +
              '<table>' + lignes + '</table>' +
              '<p>الاستمارة مرفقة بصيغة PDF. — <a href="' + v.lienPdf + '">Drive</a></p></div>',
    attachments: [pdf],
    replyTo: v.email || CONFIG.EMAIL_ECOLE,
    name: CONFIG.NOM_ECOLE,
  });

  if (CONFIG.ENVOYER_COPIE_AU_PARENT && /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(v.email)) {
    MailApp.sendEmail({
      to: v.email,
      subject: 'تأكيد التسجيل — ' + v.nomEleve,
      htmlBody: '<div dir="rtl" style="font-family:Tahoma,Arial">' +
                '<p>السلام عليكم ورحمة الله وبركاته،</p>' +
                '<p>تم استلام طلب تسجيل الطالب <b>' + echapper_(v.nomEleve) + '</b> (رقم ' + v.numero +
                ') في ' + CONFIG.NOM_ECOLE + '. تجدون نسخة من الاستمارة مرفقة.</p>' +
                '<p>سيتم التواصل معكم قريباً لتأكيد التسجيل. جزاكم الله خيراً.</p></div>',
      attachments: [pdf],
      replyTo: CONFIG.EMAIL_ECOLE,
      name: CONFIG.NOM_ECOLE,
    });
  }
}

/* ------------------------------------------------------------------ */
/* Installation & test (à lancer à la main depuis l'éditeur)           */
/* ------------------------------------------------------------------ */

/** Étape 4 du README : crée l'onglet, les en-têtes et le dossier Drive, demande les autorisations. */
function installer() {
  const sheet = onglet_();
  dossier_();
  DriveApp.getFileById(CONFIG.TEMPLATE_DOC_ID); // vérifie que l'ID du modèle est correct
  console.log('OK — onglet "' + sheet.getName() + '" prêt, quota e-mails restant aujourd\'hui : ' +
              MailApp.getRemainingDailyQuota());
}

/** Envoie une fausse inscription pour tout tester (ligne + PDF + e-mail). */
function testerInscription() {
  const r = enregistrer_({
    nomEleve: 'تجربة — أحمد بن محمد', dateNaissance: '2015-03-21', niveau: 'السنة الرابعة ابتدائي',
    adresse: 'باب الزوار، الجزائر', telEleve: '', sante: 'نعم', santeDetails: 'حساسية',
    nomTuteur: 'محمد بن علي', cniTuteur: '123456789012345678', telTuteur: '0550000000',
    email: '', dateInscription: '', accord: true,
  });
  console.log(r);
}

/* ------------------------------------------------------------------ */
/* Utilitaires                                                         */
/* ------------------------------------------------------------------ */

function onglet_() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sheet = ss.getSheetByName(CONFIG.NOM_ONGLET);
  if (!sheet) {
    sheet = ss.insertSheet(CONFIG.NOM_ONGLET);
    sheet.setRightToLeft(true);
    sheet.getRange(1, 1, 1, COLONNES.length)
      .setValues([COLONNES.map(function (c) { return c[1]; })])
      .setFontWeight('bold').setBackground('#0d5c3d').setFontColor('#ffffff');
    sheet.setFrozenRows(1);
    // Texte brut : garde le 0 des numéros de téléphone et les longs n° de carte
    sheet.getRange(2, 1, sheet.getMaxRows() - 1, COLONNES.length).setNumberFormat('@');
    sheet.autoResizeColumns(1, COLONNES.length);
  }
  return sheet;
}

function dossier_() {
  const props = PropertiesService.getScriptProperties();
  const id = props.getProperty('DOSSIER_PDF_ID');
  if (id) {
    try { return DriveApp.getFolderById(id); } catch (e) { /* supprimé : on le recrée */ }
  }
  const dossier = DriveApp.createFolder(CONFIG.NOM_DOSSIER_PDF);
  props.setProperty('DOSSIER_PDF_ID', dossier.getId());
  return dossier;
}

function prochainNumero_(date) {
  const props = PropertiesService.getScriptProperties();
  const n = Number(props.getProperty('COMPTEUR') || 0) + 1;
  props.setProperty('COMPTEUR', String(n));
  return Utilities.formatDate(date, CONFIG.FUSEAU, 'yyyy') + '-' + ('000' + n).slice(-4);
}

function nettoyer_(x) {
  if (x === undefined || x === null || typeof x === 'object') return '';
  return String(x).trim().slice(0, 500);
}

// Empêche qu'une saisie commençant par = + - @ soit interprétée comme formule
function pourSheet_(x) {
  const s = x || '';
  return /^[=+\-@]/.test(s) ? "'" + s : s;
}

function echapper_(s) {
  return String(s).replace(/[&<>"]/g, function (c) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
  });
}

function json_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}
