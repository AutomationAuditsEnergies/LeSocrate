/* eslint-disable react-refresh/only-export-components */
import React, { useLayoutEffect, useRef, useState } from 'react';
import './SalesHackingSourceDeck.css';

export const SOURCE_SLIDES = {
  "welcome": {
    "className": "slide s-welcome",
    "label": "01 Bienvenue",
    "html": "<div class=\"chrome\">\n      <div class=\"brand\"><span class=\"mark\">Sales</span><span class=\"tag\">hacking</span></div>\n    </div>\n\n    <div class=\"meta-row\">\n      <span class=\"day\">Journée 1</span>\n      <span class=\"meta-bar\"></span>\n      <span class=\"meta-note\">Lancement du parcours</span>\n    </div>\n\n    <h1>Bienvenue</h1>\n\n    <div class=\"titre\">Titre professionnel<br><span class=\"crl\">CRCD</span></div>"
  },
  "program_year": {
    "className": "slide s-prog-year",
    "label": "02 Programme annuel",
    "html": "<div class=\"chrome\">\n      <div class=\"brand\"><span class=\"mark\">Sales</span><span class=\"tag\">hacking</span></div>\n    </div>\n\n    <div class=\"py-head\">\n      <span class=\"eyebrow\">— Programme de l'année</span>\n      <h1>Parcours <span class=\"crl\">annuel.</span></h1>\n      <p class=\"sub\">Deux grands ensembles de compétences qui se complètent pour tenir toutes les facettes du poste.</p>\n    </div>\n\n    <svg class=\"py-svg-road\" viewBox=\"0 0 1920 760\" preserveAspectRatio=\"xMidYMid meet\" xmlns=\"http://www.w3.org/2000/svg\">\n      <defs>\n        <linearGradient id=\"py-paper-card\" x1=\"0\" y1=\"0\" x2=\"1\" y2=\"1\">\n          <stop offset=\"0%\" stop-color=\"#f9f3e0\"></stop>\n          <stop offset=\"58%\" stop-color=\"#ede2bc\"></stop>\n          <stop offset=\"100%\" stop-color=\"#e3d5aa\"></stop>\n        </linearGradient>\n      </defs>\n\n      <!-- Road shadow -->\n      <path d=\"M 0,380 C 160,380 340,220 520,220 C 700,220 860,380 1000,380 C 1140,380 1340,510 1560,510 C 1680,510 1820,380 1920,380\" stroke=\"rgba(0,0,20,0.55)\" stroke-width=\"120\" fill=\"none\" stroke-linecap=\"round\"></path>\n      <!-- Road surface -->\n      <path d=\"M 0,380 C 160,380 340,220 520,220 C 700,220 860,380 1000,380 C 1140,380 1340,510 1560,510 C 1680,510 1820,380 1920,380\" stroke=\"#162060\" stroke-width=\"104\" fill=\"none\" stroke-linecap=\"round\"></path>\n      <!-- Road edge lines -->\n      <path d=\"M 0,380 C 160,380 340,220 520,220 C 700,220 860,380 1000,380 C 1140,380 1340,510 1560,510 C 1680,510 1820,380 1920,380\" stroke=\"rgba(255,255,255,0.12)\" stroke-width=\"104\" fill=\"none\" stroke-linecap=\"round\"></path>\n      <!-- White center dashes -->\n      <path d=\"M 0,380 C 160,380 340,220 520,220 C 700,220 860,380 1000,380 C 1140,380 1340,510 1560,510 C 1680,510 1820,380 1920,380\" stroke=\"rgba(255,255,255,0.65)\" stroke-width=\"5\" fill=\"none\" stroke-dasharray=\"36 22\" stroke-linecap=\"round\"></path>\n\n      <!-- ── NODE 01 at (520, 220) — TOP ── -->\n      <!-- Label card 01 (above) -->\n      <rect x=\"278\" y=\"10\" width=\"504\" height=\"150\" rx=\"4\" fill=\"rgba(0,0,20,0.38)\"></rect>\n      <rect x=\"268\" y=\"0\" width=\"504\" height=\"150\" rx=\"4\" fill=\"url(#py-paper-card)\" stroke=\"rgba(10,19,58,0.10)\" stroke-width=\"1.5\"></rect>\n      <line x1=\"302\" y1=\"0\" x2=\"302\" y2=\"150\" stroke=\"rgba(210,60,60,0.32)\" stroke-width=\"2\"></line>\n      <text x=\"318\" y=\"28\" font-family=\"'JetBrains Mono',monospace\" font-size=\"15\" fill=\"#cc3b1e\" letter-spacing=\"3\">PHASE 01</text>\n      <text text-anchor=\"middle\" fill=\"#0a133a\" font-family=\"'Archivo Black',sans-serif\">\n        <tspan x=\"522\" y=\"69\" font-size=\"27\">Assistance et relation</tspan>\n        <tspan x=\"522\" dy=\"32\" font-size=\"27\">client à distance</tspan>\n      </text>\n      <text x=\"318\" y=\"132\" font-family=\"Manrope,sans-serif\" font-size=\"21\" fill=\"rgba(10,19,58,0.62)\">Accueillir, écouter, comprendre et résoudre.</text>\n      <!-- Connector -->\n      <line x1=\"520\" y1=\"154\" x2=\"520\" y2=\"178\" stroke=\"rgba(255,255,255,0.3)\" stroke-width=\"2\" stroke-dasharray=\"5 4\"></line>\n      <!-- Glow -->\n      <circle cx=\"520\" cy=\"220\" r=\"64\" fill=\"rgba(255,93,108,0.10)\"></circle>\n      <circle cx=\"520\" cy=\"220\" r=\"50\" fill=\"none\" stroke=\"rgba(255,93,108,0.35)\" stroke-width=\"2\"></circle>\n      <!-- Node -->\n      <circle cx=\"520\" cy=\"220\" r=\"40\" fill=\"#ff5d6c\"></circle>\n      <circle cx=\"520\" cy=\"220\" r=\"40\" fill=\"none\" stroke=\"rgba(255,255,255,0.22)\" stroke-width=\"4\"></circle>\n      <text x=\"520\" y=\"234\" text-anchor=\"middle\" font-family=\"'Archivo Black',sans-serif\" font-size=\"34\" font-weight=\"900\" fill=\"white\" letter-spacing=\"-0.5\">01</text>\n\n      <!-- ── NODE 02 at (1560, 510) — BOTTOM ── -->\n      <!-- Glow -->\n      <circle cx=\"1560\" cy=\"510\" r=\"64\" fill=\"rgba(255,93,108,0.10)\"></circle>\n      <circle cx=\"1560\" cy=\"510\" r=\"50\" fill=\"none\" stroke=\"rgba(255,93,108,0.35)\" stroke-width=\"2\"></circle>\n      <!-- Node -->\n      <circle cx=\"1560\" cy=\"510\" r=\"40\" fill=\"#ff5d6c\"></circle>\n      <circle cx=\"1560\" cy=\"510\" r=\"40\" fill=\"none\" stroke=\"rgba(255,255,255,0.22)\" stroke-width=\"4\"></circle>\n      <text x=\"1560\" y=\"524\" text-anchor=\"middle\" font-family=\"'Archivo Black',sans-serif\" font-size=\"34\" font-weight=\"900\" fill=\"white\" letter-spacing=\"-0.5\">02</text>\n      <!-- Connector -->\n      <line x1=\"1560\" y1=\"554\" x2=\"1560\" y2=\"586\" stroke=\"rgba(255,255,255,0.3)\" stroke-width=\"2\" stroke-dasharray=\"5 4\"></line>\n      <!-- Label card 02 (below) -->\n      <rect x=\"1318\" y=\"600\" width=\"504\" height=\"150\" rx=\"4\" fill=\"rgba(0,0,20,0.38)\"></rect>\n      <rect x=\"1308\" y=\"590\" width=\"504\" height=\"150\" rx=\"4\" fill=\"url(#py-paper-card)\" stroke=\"rgba(10,19,58,0.10)\" stroke-width=\"1.5\"></rect>\n      <line x1=\"1342\" y1=\"590\" x2=\"1342\" y2=\"740\" stroke=\"rgba(210,60,60,0.32)\" stroke-width=\"2\"></line>\n      <text x=\"1358\" y=\"618\" font-family=\"'JetBrains Mono',monospace\" font-size=\"15\" fill=\"#cc3b1e\" letter-spacing=\"3\">PHASE 02</text>\n      <text text-anchor=\"middle\" fill=\"#0a133a\" font-family=\"'Archivo Black',sans-serif\">\n        <tspan x=\"1562\" y=\"657\" font-size=\"26\">Actions commerciales</tspan>\n        <tspan x=\"1562\" dy=\"31\" font-size=\"26\">en relation client</tspan>\n      </text>\n      <text x=\"1358\" y=\"722\" font-family=\"Manrope,sans-serif\" font-size=\"21\" fill=\"rgba(10,19,58,0.62)\">Identifier un besoin et proposer une solution.</text>\n\n    </svg>"
  },
  "day_program_7_steps": {
    "className": "slide s-program",
    "label": "03 Programme journée",
    "html": "<div class=\"chrome\">\n      <div class=\"brand\"><span class=\"mark\">Sales</span><span class=\"tag\">hacking</span></div>\n    </div>\n\n    <div class=\"pg-left\">\n      <span class=\"eyebrow\">— Feuille de route</span>\n      <h1>Programme<br>de la <span class=\"crl\">journée.</span></h1>\n      <p class=\"sub\">Une journée dédiée aux <b>fondamentaux de l'échange à distance</b> — du premier contact jusqu'à l'empreinte que l'on laisse après.</p>\n    </div>\n\n    <div class=\"pg-list\">\n      <ol>\n        <li class=\"start\"><span class=\"n\">01</span><span class=\"t\">Communiquer sans visuel</span></li>\n        <li><span class=\"n\">02</span><span class=\"t\">Le ton de la voix</span></li>\n        <li><span class=\"n\">03</span><span class=\"t\">Le rythme de synchronisation</span></li>\n        <li><span class=\"n\">04</span><span class=\"t\">Humaniser l'écrit asynchrone</span></li>\n        <li><span class=\"n\">05</span><span class=\"t\">La première minute</span></li>\n        <li><span class=\"n\">06</span><span class=\"t\">L'écoute active</span></li>\n        <li><span class=\"n\">07</span><span class=\"t\">L'empreinte après contact</span></li>\n      </ol>\n    </div>"
  },
  "chapter_opener": {
    "className": "slide s-chapitre",
    "label": "04 -B Chapitre 1 ouverture",
    "html": "<div class=\"chrome\">\n      <div class=\"brand\"><span class=\"mark\">Sales</span><span class=\"tag\">hacking</span></div>\n    </div>\n\n    <div class=\"left\">\n        <h1><span class=\"ch-label\">Chapitre 1 :</span> <span class=\"ch-name\">L'obstacle invisible</span></h1>\n      </div>\n\n      <div class=\"axes\">\n        <div class=\"axe\">\n          <span class=\"num\">01</span>\n          <div class=\"content\">\n            <span class=\"t\">Le brouillard de la distance</span>\n            <span class=\"d\">Quand le client ne voit pas, son cerveau complète.</span>\n          </div>\n        </div>\n        <div class=\"axe\">\n          <span class=\"num\">02</span>\n          <div class=\"content\">\n            <span class=\"t\">Les biais de perception</span>\n            <span class=\"d\">Un silence, un ton ou un rythme devient un message.</span>\n          </div>\n        </div>\n      </div>"
  },
  "reprise_recap": {
    "className": "slide s-reprise-recap",
    "label": "05 Reprise recap",
    "html": "<div class=\"chrome\">\n      <div class=\"brand\"><span class=\"mark\">Sales</span><span class=\"tag\">hacking</span></div>\n    </div>\n    <div class=\"rr-layout\">\n      <div class=\"rr-left\">\n        <span class=\"rr-eyebrow\">— Reprise</span>\n        <h1>On reprend le <span class=\"crl\">fil.</span></h1>\n        <div class=\"rr-points rr-points--count-3\">\n          <div class=\"rr-point\"><span class=\"rr-num\">01</span><div><h3>Traduire l'écran</h3><p>Dire simplement ce que le client doit faire, sans supposer qu'il voit la même chose.</p></div></div>\n          <div class=\"rr-point\"><span class=\"rr-num\">02</span><div><h3>Reformuler</h3><p>Valider ce qui vient d'être fait avant de donner l'étape suivante.</p></div></div>\n          <div class=\"rr-point\"><span class=\"rr-num\">03</span><div><h3>Garder le cadre</h3><p>Avancer avec précision tout en restant dans les règles posées.</p></div></div>\n        </div>\n      </div>\n      <div class=\"rr-right\" aria-hidden=\"true\">\n        <div class=\"rr-card\"><span>chapitre précédent</span><strong>repères utiles</strong></div>\n      </div>\n    </div>"
  },
  "reflection": {
    "className": "slide s-reflection",
    "label": "05 Reflection — Même intention",
    "html": "<div class=\"chrome\">\n      <div class=\"brand\"><span class=\"mark\">Sales</span><span class=\"tag\">hacking</span></div>\n    </div>\n\n        <span class=\"ref-eyebrow\">— Principe clé</span>\n    <h2 class=\"ref-title\">Même intention,<br><span class=\"crl\">autre forme.</span></h2>\n    <p class=\"ref-body\">L'accueil ne change pas d'objectif selon le canal.<br>Ce qui change, c'est la <b>manière de le faire ressentir.</b></p>"
  },
  "definition": {
    "className": "slide s-def",
    "label": "06 Definition",
    "html": "<div class=\"chrome\">\n      <div class=\"brand\"><span class=\"mark\">Sales</span><span class=\"tag\">hacking</span></div>\n    </div>\n\n    <div class=\"left\">\n      <span class=\"eyebrow\">— Vocabulaire</span>\n      <h2 class=\"word\">Opération.</h2>\n    </div>\n    <div class=\"right\">\n      <div class=\"label\">DÉFINITION DE TRAVAIL</div>\n      <p class=\"body\">Un <b>système répétable</b> qui produit un résultat prévisible — sans dépendre d'une personne en particulier.</p>\n      <div class=\"tag-row\">\n        <span>RÉPÉTABLE</span>\n        <span>MESURABLE</span>\n        <span>DÉLÉGABLE</span>\n        <span>DOCUMENTÉ</span>\n      </div>\n    </div>"
  },
  "comparison": {
    "className": "slide s-diag",
    "label": "07 Diagnostic",
    "html": "<div class=\"chrome\">\n      <div class=\"brand\"><span class=\"mark\">Sales</span><span class=\"tag\">hacking</span></div>\n    </div>\n\n    <div class=\"col l\">\n      <span class=\"eyebrow\">— État actuel</span>\n      <h2>Équipe<br><span class=\"b\">épuisée.</span></h2>\n      <ul>\n        <li><span class=\"ic\">−</span>Tout passe par 2 personnes</li>\n        <li><span class=\"ic\">−</span>Aucun process écrit</li>\n        <li><span class=\"ic\">−</span>3h/jour en Slack</li>\n        <li><span class=\"ic\">−</span>Erreurs qui se répètent</li>\n      </ul>\n    </div>\n    <div class=\"col r\">\n      <span class=\"eyebrow\">— Objectif 7 semaines</span>\n      <h2>Équipe<br><span class=\"accent\">autonome.</span></h2>\n      <ul>\n        <li><span class=\"ic\">✓</span>Décisions distribuées</li>\n        <li><span class=\"ic\">✓</span>12 SOPs documentées</li>\n        <li><span class=\"ic\">✓</span>Slack divisé par 4</li>\n        <li><span class=\"ic\">✓</span>Erreurs trackées + résolues</li>\n      </ul>\n    </div>"
  },
  "warning": {
    "className": "slide s-warning-note",
    "label": "08 Warning — Automatiser le chaos",
    "html": "<div class=\"chrome\">\n      <div class=\"brand\"><span class=\"mark\">Sales</span><span class=\"tag\">hacking</span></div>\n    </div>\n\n    <div class=\"wn-inner\">\n\n      <!-- Post-it SVG — élargi pour contenir \"Attention !\" -->\n      <div class=\"wn-sticky\">\n        <svg viewBox=\"0 0 500 420\" width=\"500\" height=\"420\" fill=\"none\" xmlns=\"http://www.w3.org/2000/svg\">\n          <!-- Drop shadow -->\n          <rect x=\"20\" y=\"24\" width=\"458\" height=\"382\" rx=\"4\" fill=\"rgba(0,0,30,0.45)\" transform=\"rotate(2,249,215)\"></rect>\n          <!-- Note body -->\n          <rect x=\"14\" y=\"12\" width=\"458\" height=\"382\" rx=\"4\" fill=\"#f5e87c\" transform=\"rotate(-1.5,243,203)\"></rect>\n          <!-- Ruled lines -->\n          <line x1=\"50\" y1=\"148\" x2=\"448\" y2=\"144\" stroke=\"rgba(0,0,80,0.08)\" stroke-width=\"1.5\"></line>\n          <line x1=\"50\" y1=\"188\" x2=\"448\" y2=\"184\" stroke=\"rgba(0,0,80,0.06)\" stroke-width=\"1\"></line>\n          <line x1=\"50\" y1=\"226\" x2=\"448\" y2=\"222\" stroke=\"rgba(0,0,80,0.06)\" stroke-width=\"1\"></line>\n          <!-- Pushpin shadow -->\n          <ellipse cx=\"253\" cy=\"36\" rx=\"14\" ry=\"6\" fill=\"rgba(0,0,30,0.3)\" transform=\"translate(3,6)\"></ellipse>\n          <!-- Pushpin body -->\n          <circle cx=\"251\" cy=\"30\" r=\"20\" fill=\"#cc1a2a\"></circle>\n          <circle cx=\"251\" cy=\"30\" r=\"13\" fill=\"#ff5d6c\"></circle>\n          <circle cx=\"247\" cy=\"26\" r=\"5\" fill=\"rgba(255,255,255,0.45)\"></circle>\n          <!-- Pushpin needle -->\n          <line x1=\"251\" y1=\"48\" x2=\"251\" y2=\"66\" stroke=\"#7a0e1a\" stroke-width=\"5\" stroke-linecap=\"round\"></line>\n          <!-- \"Attention !\" — contraint en largeur -->\n          <text x=\"247\" y=\"220\" text-anchor=\"middle\" font-family=\"Caveat,cursive\" font-size=\"88\" fill=\"#cc1a2a\" textLength=\"380\" lengthAdjust=\"spacing\" transform=\"rotate(-1.5,247,220)\">Attention !</text>\n        </svg>\n      </div>\n\n      <!-- Text à droite -->\n      <div class=\"wn-text\">\n        <span class=\"eyebrow\">— Erreur fréquente</span>\n        <h1>Automatiser <span class=\"crl\">le chaos.</span></h1>\n        <div class=\"wn-body\">\n          <span class=\"lbl\">Pourquoi</span>\n          <p>Brancher une IA sur un process bancal <b>multiplie le désordre à la vitesse de la machine.</b> Documentez d'abord, automatisez ensuite.</p>\n        </div>\n      </div>\n\n    </div>"
  },
  "casestudy": {
    "className": "slide s-casestudy",
    "label": "09 Casestudy — Codes d'accueil",
    "html": "<div class=\"chrome\">\n      <div class=\"brand\"><span class=\"mark\">Sales</span><span class=\"tag\">hacking</span></div>\n    </div>\n\n    <div class=\"cs-head\">\n      <span class=\"eyebrow\">— Analyse comparative</span>\n      <h1>Les codes d'accueil<br><span class=\"crl\">selon le canal.</span></h1>\n    </div>\n\n    <div class=\"cs-cards cols-3 paper\">\n      <div class=\"cs-card accent-coral\">\n        <div class=\"cs-stripe\"></div>\n        <div class=\"cs-body\">\n          <span class=\"cs-tag\">01 · Téléphone</span>\n          <h3 class=\"cs-title\">La voix en direct</h3>\n          <div class=\"cs-sep\"></div>\n          <p class=\"cs-text\">L'accueil se joue dans les <b>premières secondes.</b> Ton, rythme et articulation remplacent le visuel.</p>\n          <span class=\"cs-example\">« Bonjour, société X, Amelle, bonjour. »</span>\n        </div>\n      </div>\n\n      <div class=\"cs-card accent-gold\">\n        <div class=\"cs-stripe\"></div>\n        <div class=\"cs-body\">\n          <span class=\"cs-tag\">02 · Email</span>\n          <h3 class=\"cs-title\">L'écrit posé</h3>\n          <div class=\"cs-sep\"></div>\n          <p class=\"cs-text\">La formule doit être <b>courte et personnalisée.</b> Le client lit en diagonale : le prénom et le motif doivent sauter aux yeux.</p>\n          <span class=\"cs-example\">« Bonjour [Prénom], suite à votre demande... »</span>\n        </div>\n      </div>\n\n      <div class=\"cs-card accent-green\">\n        <div class=\"cs-stripe\"></div>\n        <div class=\"cs-body\">\n          <span class=\"cs-tag\">03 · Chat</span>\n          <h3 class=\"cs-title\">L'écrit immédiat</h3>\n          <div class=\"cs-sep\"></div>\n          <p class=\"cs-text\">La réponse doit être <b>rapide et fluide.</b> Pas de bloc de texte : une phrase d'accueil, puis une question courte.</p>\n          <span class=\"cs-example\">« Bonjour ! En quoi puis-je vous aider ? »</span>\n        </div>\n      </div>\n    </div>"
  },
  "steps": {
    "className": "slide s-process",
    "label": "10 Process — 4 étapes délégables",
    "html": "<div class=\"chrome\">\n      <div class=\"brand\"><span class=\"mark\">Sales</span><span class=\"tag\">hacking</span></div>\n    </div>\n\n    <div class=\"head\">\n      <span class=\"eyebrow\">— Méthode O.D.A.M.</span>\n      <h1>4 étapes pour rendre<br>un process <span class=\"crl\">délégable.</span></h1>\n    </div>\n\n    <div class=\"steps\">\n      <div class=\"step active\">\n        <div class=\"dot\">01</div>\n        <h3>Observer</h3>\n        <p>Filmer 5 fois la tâche réelle.</p>\n      </div>\n      <div class=\"step\">\n        <div class=\"dot\">02</div>\n        <h3>Découper</h3>\n        <p>Identifier décisions, actions répétables et exceptions.</p>\n      </div>\n      <div class=\"step\">\n        <div class=\"dot\">03</div>\n        <h3>Automatiser</h3>\n        <p>Brancher l'IA uniquement sur les segments stables.</p>\n      </div>\n      <div class=\"step\">\n        <div class=\"dot\">04</div>\n        <h3>Mesurer</h3>\n        <p>Définir 1 KPI par étape.</p>\n      </div>\n    </div>"
  },
  "recap": {
    "className": "slide s-recap2",
    "label": "11 Récap — Ce qu'on retient",
    "html": "<div class=\"chrome\">\n      <div class=\"brand\"><span class=\"mark\">Sales</span><span class=\"tag\">hacking</span></div>\n    </div>\n\n    <div class=\"rc2-layout\">\n\n      <!-- LEFT -->\n      <div class=\"rc2-left\">\n        <div class=\"rc2-head\">\n          <h1>Ce qu'on<br><span class=\"o\">retient.</span></h1>\n        </div>\n        <div class=\"rc2-cards\">\n          <div class=\"rc2-card\" style=\"--card-color:#ff6b47\">\n            <div class=\"rc2-num-badge\">01</div>\n            <h3>Process avant outils</h3>\n            <div class=\"rc2-line\"></div>\n            <p>L'outil amplifie ce qui existe. Un process bancal reste bancal — juste plus vite.</p>\n          </div>\n          <div class=\"rc2-card\" style=\"--card-color:#f5a623\">\n            <div class=\"rc2-num-badge\">02</div>\n            <h3>Filmer la réalité</h3>\n            <div class=\"rc2-line\"></div>\n            <p>Observer avant de prescrire. La tâche réelle est toujours différente de la tâche imaginée.</p>\n          </div>\n          <div class=\"rc2-card\" style=\"--card-color:#1e40af\">\n            <div class=\"rc2-num-badge\">03</div>\n            <h3>Mesurer ou tâtonner</h3>\n            <div class=\"rc2-line\"></div>\n            <p>1 chiffre par étape. Sans mesure, impossible de savoir si l'amélioration est réelle.</p>\n          </div>\n        </div>\n      </div>\n\n      <!-- RIGHT — Cible SVG -->\n      <div class=\"rc2-right\">\n        <!-- Déco circles -->\n        <div class=\"rc2-deco rc2-d1\"></div>\n        <div class=\"rc2-deco rc2-d2\"></div>\n        <div class=\"rc2-deco rc2-d3\"></div>\n        <div class=\"rc2-deco rc2-d4\"></div>\n        <!-- Plus signs -->\n        <svg class=\"rc2-plus p1\" width=\"36\" height=\"36\" viewBox=\"0 0 36 36\"><line x1=\"18\" y1=\"0\" x2=\"18\" y2=\"36\" stroke=\"#ff6b47\" stroke-width=\"5\" stroke-linecap=\"round\"></line><line x1=\"0\" y1=\"18\" x2=\"36\" y2=\"18\" stroke=\"#ff6b47\" stroke-width=\"5\" stroke-linecap=\"round\"></line></svg>\n        <svg class=\"rc2-plus p2\" width=\"28\" height=\"28\" viewBox=\"0 0 28 28\"><line x1=\"14\" y1=\"0\" x2=\"14\" y2=\"28\" stroke=\"rgba(255,255,255,0.35)\" stroke-width=\"4\" stroke-linecap=\"round\"></line><line x1=\"0\" y1=\"14\" x2=\"28\" y2=\"14\" stroke=\"rgba(255,255,255,0.35)\" stroke-width=\"4\" stroke-linecap=\"round\"></line></svg>\n        <svg class=\"rc2-plus p3\" width=\"28\" height=\"28\" viewBox=\"0 0 28 28\"><line x1=\"14\" y1=\"0\" x2=\"14\" y2=\"28\" stroke=\"var(--coral)\" stroke-width=\"4\" stroke-linecap=\"round\"></line><line x1=\"0\" y1=\"14\" x2=\"28\" y2=\"14\" stroke=\"var(--coral)\" stroke-width=\"4\" stroke-linecap=\"round\"></line></svg>\n\n        <!-- Target SVG -->\n        <svg class=\"rc2-target\" viewBox=\"0 0 500 500\" xmlns=\"http://www.w3.org/2000/svg\">\n          <!-- Shadow disc -->\n          <ellipse cx=\"258\" cy=\"476\" rx=\"180\" ry=\"22\" fill=\"rgba(0,0,20,0.45)\"></ellipse>\n          <!-- Outer ring 1 — very dark navy -->\n          <circle cx=\"250\" cy=\"250\" r=\"230\" fill=\"#0a1060\"></circle>\n          <!-- Ring 2 -->\n          <circle cx=\"250\" cy=\"250\" r=\"190\" fill=\"#0d1880\"></circle>\n          <!-- Ring 3 -->\n          <circle cx=\"250\" cy=\"250\" r=\"150\" fill=\"#1a2a9a\"></circle>\n          <!-- Ring 4 coral light -->\n          <circle cx=\"250\" cy=\"250\" r=\"110\" fill=\"#f4967a\"></circle>\n          <!-- Ring 5 coral -->\n          <circle cx=\"250\" cy=\"250\" r=\"72\" fill=\"#ff6b47\"></circle>\n          <!-- Bullseye -->\n          <circle cx=\"250\" cy=\"250\" r=\"38\" fill=\"#cc3b1e\"></circle>\n          <!-- Shine on bullseye -->\n          <ellipse cx=\"238\" cy=\"237\" rx=\"14\" ry=\"9\" fill=\"rgba(255,255,255,0.22)\" transform=\"rotate(-20 238 237)\"></ellipse>\n          <!-- Highlight arc on outer ring -->\n          <path d=\"M 90,180 A 190,190 0 0,1 250,60\" stroke=\"rgba(255,255,255,0.10)\" stroke-width=\"28\" fill=\"none\" stroke-linecap=\"round\"></path>\n\n          <!-- Arrow shaft -->\n          <line x1=\"30\" y1=\"470\" x2=\"245\" y2=\"255\" stroke=\"#0a1060\" stroke-width=\"18\" stroke-linecap=\"round\"></line>\n          <!-- Arrow head -->\n          <polygon points=\"245,255 230,278 268,260\" fill=\"#0a1060\"></polygon>\n          <!-- Arrow feathers -->\n          <path d=\"M30,470 L10,445 L38,455 Z\" fill=\"#0a1060\"></path>\n          <path d=\"M50,450 L28,428 L56,437 Z\" fill=\"#1a2a9a\"></path>\n          <!-- Arrow shaft highlight -->\n          <line x1=\"32\" y1=\"468\" x2=\"243\" y2=\"258\" stroke=\"rgba(255,255,255,0.12)\" stroke-width=\"6\" stroke-linecap=\"round\"></line>\n        </svg>\n      </div>\n\n    </div>"
  },
  "pause": {
    "className": "slide s-pause",
    "label": "12 Pause",
    "html": "<div class=\"chrome\">\n      <div class=\"brand\"><span class=\"mark\">Sales</span><span class=\"tag\">hacking</span></div>\n    </div>\n\n    <div class=\"ring r3\"></div>\n    <div class=\"ring r2\"></div>\n    <div class=\"ring\"></div>\n\n    <div class=\"wrap\">\n      <span class=\"eyebrow\">— On respire</span>\n      <h1>Pause.<br><span class=\"o\">5 minutes.</span></h1>\n      <div class=\"sub\">notez ce qui vous a marqué jusqu'ici.</div>\n    </div>"
  },
  "qa": {
    "className": "slide s-qa",
    "label": "13 Q&amp;A",
    "html": "<div class=\"chrome\">\n      <div class=\"brand\"><span class=\"mark\">Sales</span><span class=\"tag\">hacking</span></div>\n    </div>\n\n    <div class=\"left\">\n      <span class=\"eyebrow\">— Vos questions, en direct</span>\n      <div class=\"qmark\">?</div>\n      <h1>On répond<br>à tout.</h1>\n    </div>\n    <div class=\"right\">\n      <div class=\"qcard\">\n        <div class=\"av\">?</div>\n        <div class=\"txt\">Comment identifier rapidement le vrai besoin d'un client sans lui donner l'impression de l'interroger ?</div>\n        <div class=\"time\">il y a 12s</div>\n      </div>\n      <div class=\"qcard\">\n        <div class=\"av b2\">?</div>\n        <div class=\"txt\">Que faire quand un client hésite entre deux produits mais ne formule pas clairement son objection ?</div>\n        <div class=\"time\">il y a 38s</div>\n      </div>\n      <div class=\"qcard\">\n        <div class=\"av b3\">?</div>\n        <div class=\"txt\">Comment proposer une vente complémentaire sans paraître insistant ou trop commercial ?</div>\n        <div class=\"time\">il y a 1m</div>\n      </div>\n      <div class=\"input\">\n        <span class=\"ph\">Posez votre question…</span>\n        <span class=\"btn\">ENVOYER</span>\n      </div>\n    </div>"
  },
  "quotable": {
    "className": "slide s-journal",
    "label": "14 Quote — Capacité doublée",
    "html": "<div class=\"chrome\">\n      <div class=\"brand\"><span class=\"mark\">Sales</span><span class=\"tag\">hacking</span></div>\n    </div>\n\n    <div class=\"jnl-scene\">\n\n      <!-- Parchment page -->\n      <div class=\"jnl-page\">\n        <div class=\"jnl-lines\"></div>\n        <div class=\"jnl-margin\"></div>\n        <div class=\"jnl-content\">\n          <p class=\"jnl-q1\">On a doublé la capacité de l'équipe<br>sans recruter.</p>\n          <p class=\"jnl-q2\">Le secret ? Arrêter de tout<br>faire passer par nous.</p>\n        </div>\n      </div></div>"
  },
  "tip": {
    "className": "slide s-tip",
    "label": "15 Tip — Flexibilité",
    "html": "<div class=\"chrome\">\n      <div class=\"brand\"><span class=\"mark\">Sales</span><span class=\"tag\">hacking</span></div>\n    </div>\n    <div class=\"card\">\n      <span class=\"badge\">CONSEIL</span>\n      <h2>Un client n'est jamais figé dans un profil.</h2>\n      <p>Restez à l'écoute et ajustez votre posture en continu. La flexibilité n'est pas une faiblesse — c'est la marque d'un conseiller qui pilote vraiment l'échange.</p>\n    </div>"
  },
  "situations": {
    "className": "slide s-situ",
    "label": "16 Trois situations",
    "html": "<div class=\"chrome\">\n      <div class=\"brand\"><span class=\"mark\">Sales</span><span class=\"tag\">hacking</span></div>\n    </div>\n\n    <div class=\"heading\">\n      <span class=\"eyebrow\">— Adapter sa posture</span>\n      <h1>Trois situations<br><span class=\"crl\">client.</span></h1>\n    </div>\n\n    <div class=\"cards\">\n      <div class=\"card a\">\n        <div class=\"stamp\">SITUATION · A</div>\n        <div class=\"t\">Client<br>pressé.</div>\n        <div class=\"d\">Prioriser l'essentiel et aller droit au résultat. Pas de préambule, pas de tour de chauffe.</div>\n        <div class=\"badge\">1</div>\n      </div>\n      <div class=\"card b\">\n        <div class=\"stamp\">SITUATION · B</div>\n        <div class=\"t\">Client<br>hésitant.</div>\n        <div class=\"d\">Clarifier le besoin avant de proposer quoi que ce soit. Le silence est un outil, pas un vide.</div>\n        <div class=\"badge\">2</div>\n      </div>\n      <div class=\"card c\">\n        <div class=\"stamp\">SITUATION · C</div>\n        <div class=\"t\">Client<br>mécontent.</div>\n        <div class=\"d\">Traiter l'émotion avant la procédure. Reconnaître, puis seulement après, agir.</div>\n        <div class=\"badge\">3</div>\n      </div>\n    </div>"
  },
  "flow": {
    "className": "slide s-flow s-flow--count-4",
    "label": "17 Traiter une demande",
    "html": "<div class=\"chrome\">\n      <div class=\"brand\"><span class=\"mark\">Sales</span><span class=\"tag\">hacking</span></div>\n    </div>\n\n    <div class=\"head\">\n      <span class=\"eyebrow\">— Le flux en quatre temps</span>\n      <h1>Traiter<br>une <span class=\"crl\">demande.</span></h1>\n    </div>\n\n    <div class=\"row\">\n      <div class=\"step\">\n        <div class=\"tile c1\">\n          <!-- target icon -->\n          <svg viewBox=\"0 0 64 64\" fill=\"none\" stroke=\"#1a1f3a\" stroke-width=\"4\" stroke-linecap=\"round\" stroke-linejoin=\"round\">\n            <circle cx=\"32\" cy=\"32\" r=\"24\"></circle>\n            <circle cx=\"32\" cy=\"32\" r=\"14\"></circle>\n            <circle cx=\"32\" cy=\"32\" r=\"4\" fill=\"#1a1f3a\"></circle>\n          </svg>\n        </div>\n        <div class=\"t\">Identifier</div>\n        <div class=\"d\">Comprendre le besoin exprimé.</div>\n      </div>\n\n      <div class=\"arrow\">\n        <svg viewBox=\"0 0 70 36\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"5\" stroke-linecap=\"round\" stroke-linejoin=\"round\">\n          <line x1=\"6\" y1=\"18\" x2=\"60\" y2=\"18\"></line>\n          <polyline points=\"48,6 62,18 48,30\"></polyline>\n        </svg>\n      </div>\n\n      <div class=\"step\">\n        <div class=\"tile c2\">\n          <!-- gear icon -->\n          <svg viewBox=\"0 0 64 64\" fill=\"none\" stroke=\"#1a1f3a\" stroke-width=\"4\" stroke-linecap=\"round\" stroke-linejoin=\"round\">\n            <circle cx=\"32\" cy=\"32\" r=\"9\"></circle>\n            <path d=\"M32 8 v8 M32 48 v8 M8 32 h8 M48 32 h8 M15 15 l6 6 M43 43 l6 6 M15 49 l6 -6 M43 21 l6 -6\"></path>\n          </svg>\n        </div>\n        <div class=\"t\">Qualifier</div>\n        <div class=\"d\">Vérifier les contraintes utiles.</div>\n      </div>\n\n      <div class=\"arrow\">\n        <svg viewBox=\"0 0 70 36\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"5\" stroke-linecap=\"round\" stroke-linejoin=\"round\">\n          <line x1=\"6\" y1=\"18\" x2=\"60\" y2=\"18\"></line>\n          <polyline points=\"48,6 62,18 48,30\"></polyline>\n        </svg>\n      </div>\n\n      <div class=\"step\">\n        <div class=\"tile c3\">\n          <!-- bolt icon -->\n          <svg viewBox=\"0 0 64 64\" fill=\"#1a1f3a\" stroke=\"#1a1f3a\" stroke-width=\"3\" stroke-linejoin=\"round\">\n            <polygon points=\"36,6 14,36 30,36 26,58 50,26 34,26\"></polygon>\n          </svg>\n        </div>\n        <div class=\"t\">Agir</div>\n        <div class=\"d\">Proposer une réponse concrète.</div>\n      </div>\n\n      <div class=\"arrow\">\n        <svg viewBox=\"0 0 70 36\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"5\" stroke-linecap=\"round\" stroke-linejoin=\"round\">\n          <line x1=\"6\" y1=\"18\" x2=\"60\" y2=\"18\"></line>\n          <polyline points=\"48,6 62,18 48,30\"></polyline>\n        </svg>\n      </div>\n\n      <div class=\"step\">\n        <div class=\"tile c4\">\n          <!-- flag icon -->\n          <svg viewBox=\"0 0 64 64\" fill=\"none\" stroke=\"#1a1f3a\" stroke-width=\"4\" stroke-linecap=\"round\" stroke-linejoin=\"round\">\n            <line x1=\"16\" y1=\"8\" x2=\"16\" y2=\"58\"></line>\n            <path d=\"M16 12 L48 12 L42 22 L48 32 L16 32 Z\" fill=\"#1a1f3a\" stroke=\"none\"></path>\n          </svg>\n        </div>\n        <div class=\"t\">Clore</div>\n        <div class=\"d\">Confirmer la suite avec précision.</div>\n      </div>\n    </div>"
  },
  "story": {
    "className": "slide s-board",
    "label": "18 Story — Le client qui revient",
    "html": "<div class=\"chrome\">\n      <div class=\"brand\"><span class=\"mark\">Sales</span><span class=\"tag\">hacking</span></div>\n    </div>\n\n    <div class=\"meta\">\n      <span class=\"bar\"></span>\n      <span class=\"chapter\">Le client qui revient</span>\n    </div>\n\n    <div class=\"chalkboard\">\n      <div class=\"board-inner\">\n        <div class=\"ch-lines\">\n          <p class=\"ch-para\">Un client qui répète la <em>même</em> demande signale souvent que la première réponse <span class=\"pink\">n'était pas assez claire</span>.</p>\n        </div>\n      </div>\n      <div class=\"tray\">\n        <span class=\"chalk w\"></span>\n        <span class=\"chalk y\"></span>\n        <span class=\"chalk p\"></span>\n        <span class=\"eraser\"></span>\n      </div>\n    </div>\n\n    <div class=\"board-morale\">\n      <span class=\"lbl\">↳ Morale</span>\n      <span class=\"text\">La <b>clarté</b> évite la répétition. Et protège la relation.</span>\n    </div>"
  },
  "analogy": {
    "className": "slide s-analogy",
    "label": "19 Analogy — CRM Carnet de bord",
    "html": "<div class=\"chrome\" style=\"position:absolute;top:40px;left:60px;z-index:30;\">\n      <div class=\"brand\"><span class=\"mark\">Sales</span><span class=\"tag\">hacking</span></div>\n    </div>\n\n    <!-- Diagonal bar -->\n    <div class=\"an-diag\"></div>\n\n    <!-- LEFT: Concept -->\n    <div class=\"an-left\">\n      <span class=\"an-tag\">— Le concept</span>\n      <h2 class=\"an-name\">CRM</h2>\n      <p class=\"an-text\">Outil de suivi centralisé de toutes les interactions — historique, étapes, relances et prochaines actions.</p>\n    </div>\n\n    <!-- RIGHT: Analogie -->\n    <div class=\"an-right\">\n      <span class=\"an-tag\">— L'analogie</span>\n      <h2 class=\"an-name\">Carnet<br>de bord</h2>\n      <p class=\"an-text\">Comme un carnet de bord, le CRM sert à comprendre ce qui s'est passé et quelle est la prochaine étape.</p>\n    </div>"
  },
  "framework": {
    "className": "slide s-fw tpl",
    "label": "20 Framework 4",
    "html": "<div class=\"chrome\">\n      <div class=\"brand\"><span class=\"mark\">Sales</span><span class=\"tag\">hacking</span></div>\n    </div>\n    <div class=\"head\">\n      <span class=\"eyebrow\">— Modèle d'analyse</span>\n      <h1>Les 4 forces de la <span class=\"crl\">performance.</span></h1>\n    </div>\n    <div class=\"wheel\">\n      <svg class=\"dial\" viewBox=\"0 0 260 260\">\n        <circle cx=\"130\" cy=\"130\" r=\"120\" fill=\"none\" stroke=\"rgba(255,255,255,0.2)\" stroke-width=\"2\"></circle>\n        <g fill=\"none\" stroke=\"rgba(255,255,255,0.18)\" stroke-width=\"1.5\">\n          <line x1=\"130\" y1=\"10\" x2=\"130\" y2=\"250\"></line>\n          <line x1=\"10\" y1=\"130\" x2=\"250\" y2=\"130\"></line>\n        </g>\n      </svg>\n      <div class=\"center\"></div>\n      <div class=\"sat s1\"><div class=\"t\">Volume</div><div class=\"d\">Nombre de contacts initiés et qualifiés par semaine.</div></div>\n      <div class=\"sat s2\"><div class=\"t\">Qualité</div><div class=\"d\">Pertinence du ciblage et précision du message envoyé.</div></div>\n      <div class=\"sat s3\"><div class=\"t\">Cadence</div><div class=\"d\">Régularité des relances et capacité à tenir la durée.</div></div>\n      <div class=\"sat s4\"><div class=\"t\">Closing</div><div class=\"d\">Habileté à demander l'engagement et à conclure.</div></div>\n    </div>"
  },
  "opinion": {
    "className": "slide s-opinion",
    "label": "21 Opinion — Qualité dans les détails",
    "html": "<div class=\"chrome\">\n      <div class=\"brand\"><span class=\"mark\">Sales</span><span class=\"tag\">hacking</span></div>\n    </div>\n    <div class=\"l\">\n      <span class=\"badge\">POINT DE VUE</span>\n      <h1>La qualité se voit<br>dans les <span class=\"crl\">détails.</span></h1>\n    </div>\n    <div class=\"r\">\n      <p>Une procédure bien suivie ne remplace pas la posture. Les deux doivent avancer ensemble. C'est la combinaison des deux qui produit une relation client durable.</p>\n    </div>"
  }
};

const SOURCE_CHROME_HTML = `<div class="chrome">
      <div class="brand"><span class="mark">Sales</span><span class="tag">hacking</span></div>
    </div>`;

const escapeSourceHtml = (value = '') => String(value || '')
  .replace(/&/g, '&amp;')
  .replace(/</g, '&lt;')
  .replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;');

const sourceAccentTitleHtml = (value = '', fallback = '') => {
  const words = String(value || fallback || '').trim().split(/\s+/).filter(Boolean);
  if (words.length < 2) return escapeSourceHtml(value || fallback);
  const last = words.pop();
  return `${escapeSourceHtml(words.join(' '))} <span class="crl">${escapeSourceHtml(last)}</span>`;
};

const variantCount = (items) => Math.min(4, Math.max(2, items.length || 3));

const casestudyVariantHtml = ({ title, eyebrow, cases }) => {
  const accents = ['accent-coral', 'accent-gold', 'accent-green', 'accent-blue'];
  return `${SOURCE_CHROME_HTML}
    <div class="cs-head">
      <span class="eyebrow">— ${escapeSourceHtml(eyebrow)}</span>
      <h1>${sourceAccentTitleHtml(title, 'Cas terrain')}</h1>
    </div>

    <div class="cs-cards cols-${variantCount(cases)} paper">
      ${cases.map((item, index) => `<div class="cs-card ${accents[index % accents.length]}">
        <div class="cs-stripe"></div>
        <div class="cs-body">
          <span class="cs-tag">${escapeSourceHtml(item.tag || `${String(index + 1).padStart(2, '0')} · Cas`)}</span>
          <h3 class="cs-title">${escapeSourceHtml(item.title)}</h3>
          <div class="cs-sep"></div>
          <p class="cs-text">${escapeSourceHtml(item.desc)}</p>
          ${item.example ? `<span class="cs-example">« ${escapeSourceHtml(item.example)} »</span>` : ''}
        </div>
      </div>`).join('\n')}
    </div>`;
};

const processVariantHtml = ({ title, eyebrow, steps }) => `${SOURCE_CHROME_HTML}
    <div class="head">
      <span class="eyebrow">— ${escapeSourceHtml(eyebrow)}</span>
      <h1>${sourceAccentTitleHtml(title, 'Les étapes clés')}</h1>
    </div>

    <div class="steps">
      ${steps.map((item, index) => `<div class="step ${index === 0 ? 'active' : ''}">
        <div class="dot">${String(index + 1).padStart(2, '0')}</div>
        <h3 class="t">${escapeSourceHtml(item.title)}</h3>
        <p class="d">${escapeSourceHtml(item.desc)}</p>
      </div>`).join('\n')}
    </div>`;

const flowIconHtml = (index) => {
  const icons = [
    '<circle cx="32" cy="32" r="24"></circle><circle cx="32" cy="32" r="14"></circle><circle cx="32" cy="32" r="4" fill="#1a1f3a"></circle>',
    '<circle cx="32" cy="32" r="9"></circle><path d="M32 8 v8 M32 48 v8 M8 32 h8 M48 32 h8 M15 15 l6 6 M43 43 l6 6 M15 49 l6 -6 M43 21 l6 -6"></path>',
    '<polygon points="36,6 14,36 30,36 26,58 50,26 34,26"></polygon>',
    '<line x1="16" y1="8" x2="16" y2="58"></line><path d="M16 12 L48 12 L42 22 L48 32 L16 32 Z" fill="#1a1f3a" stroke="none"></path>',
  ];
  const fill = index === 2 ? ' fill="#1a1f3a"' : ' fill="none"';
  return `<svg viewBox="0 0 64 64"${fill} stroke="#1a1f3a" stroke-width="4" stroke-linecap="round" stroke-linejoin="round">${icons[index % icons.length]}</svg>`;
};

const flowVariantHtml = ({ title, eyebrow, steps }) => `${SOURCE_CHROME_HTML}
    <div class="head">
      <span class="eyebrow">— ${escapeSourceHtml(eyebrow)}</span>
      <h1>${sourceAccentTitleHtml(title, 'Traiter une demande.')}</h1>
    </div>

    <div class="row">
      ${steps.map((item, index) => `<div class="step">
        <div class="tile c${index + 1}">
          ${flowIconHtml(index)}
        </div>
        <div class="t">${escapeSourceHtml(item.title)}</div>
        <div class="d">${escapeSourceHtml(item.desc)}</div>
      </div>${index < steps.length - 1 ? `

      <div class="arrow">
        <svg viewBox="0 0 70 36" fill="none" stroke="currentColor" stroke-width="5" stroke-linecap="round" stroke-linejoin="round">
          <line x1="6" y1="18" x2="60" y2="18"></line>
          <polyline points="48,6 62,18 48,30"></polyline>
        </svg>
      </div>` : ''}`).join('\n')}
    </div>`;

const recapVariantHtml = ({ title, points }) => {
  const colors = ['#ff6b47', '#f5a623', '#1e40af', '#58e2a4'];
  return `${SOURCE_CHROME_HTML}
    <div class="rc2-layout">
      <div class="rc2-left">
        <div class="rc2-head">
          <h1>${sourceAccentTitleHtml(title, "Ce qu'on retient.")}</h1>
        </div>
        <div class="rc2-cards rc2-cards--count-${variantCount(points)}">
          ${points.map((item, index) => `<div class="rc2-card" style="--card-color:${colors[index % colors.length]}">
            <div class="rc2-num-badge">${String(index + 1).padStart(2, '0')}</div>
            <h3>${escapeSourceHtml(item.title)}</h3>
            <div class="rc2-line"></div>
            <p>${escapeSourceHtml(item.desc)}</p>
          </div>`).join('\n')}
        </div>
      </div>
      <div class="rc2-right">
        <div class="rc2-deco rc2-d1"></div>
        <div class="rc2-deco rc2-d2"></div>
        <div class="rc2-deco rc2-d3"></div>
        <div class="rc2-deco rc2-d4"></div>
        <svg class="rc2-target" viewBox="0 0 500 500" xmlns="http://www.w3.org/2000/svg">
          <ellipse cx="258" cy="476" rx="180" ry="22" fill="rgba(0,0,20,0.45)"></ellipse>
          <circle cx="250" cy="250" r="230" fill="#0a1060"></circle>
          <circle cx="250" cy="250" r="184" fill="#0d1880"></circle>
          <circle cx="250" cy="250" r="138" fill="#1a2a9a"></circle>
          <circle cx="250" cy="250" r="92" fill="#ff6b47"></circle>
          <circle cx="250" cy="250" r="38" fill="#cc3b1e"></circle>
          <path d="M 90,180 A 190,190 0 0,1 250,60" stroke="rgba(255,255,255,0.10)" stroke-width="28" fill="none" stroke-linecap="round"></path>
          <line x1="30" y1="470" x2="245" y2="255" stroke="#0a1060" stroke-width="18" stroke-linecap="round"></line>
          <polygon points="245,255 230,278 268,260" fill="#0a1060"></polygon>
        </svg>
      </div>
    </div>`;
};

const situationsVariantHtml = ({ title, eyebrow, items }) => {
  const classes = ['a', 'b', 'c', 'd'];
  return `${SOURCE_CHROME_HTML}
    <div class="heading">
      <span class="eyebrow">— ${escapeSourceHtml(eyebrow)}</span>
      <h1>${sourceAccentTitleHtml(title, 'Situations client')}</h1>
    </div>

    <div class="cards">
      ${items.map((item, index) => `<div class="card ${classes[index % classes.length]}">
        <div class="stamp">SITUATION · ${String.fromCharCode(65 + index)}</div>
        <div class="t">${escapeSourceHtml(item.title)}</div>
        <div class="d">${escapeSourceHtml(item.desc)}</div>
        <div class="badge">${index + 1}</div>
      </div>`).join('\n')}
    </div>`;
};

export const SOURCE_SLIDE_VARIANTS = {
  casestudy_2: {
    templateId: 'casestudy',
    className: 'slide s-casestudy',
    label: '09A Casestudy · 2 cartes',
    html: casestudyVariantHtml({
      title: "Deux canaux d'accueil",
      eyebrow: 'Analyse comparative',
      cases: [
        { tag: '01 · Téléphone', title: 'Voix en direct', desc: "Le client perçoit l'attention dans le rythme, le sourire vocal et la clarté immédiate.", example: 'Bonjour, société X, Amelle, bonjour.' },
        { tag: '02 · Courriel', title: 'Écrit posé', desc: "Le client cherche un objet clair, une phrase d'accueil courte et une prochaine étape visible.", example: 'Bonjour Nadia, suite à votre demande.' },
      ],
    }),
  },
  casestudy_4: {
    templateId: 'casestudy',
    className: 'slide s-casestudy',
    label: '09B Casestudy · 4 cartes',
    html: casestudyVariantHtml({
      title: "Quatre contextes d'accueil",
      eyebrow: 'Analyse comparative',
      cases: [
        { tag: '01 · Appel', title: 'Direct', desc: "Installer la présence dès les premières secondes.", example: 'Je vous écoute.' },
        { tag: '02 · Email', title: 'Traçable', desc: "Rendre la demande lisible et exploitable.", example: 'Je récapitule.' },
        { tag: '03 · Chat', title: 'Rapide', desc: "Répondre court, puis demander la précision utile.", example: 'Quel numéro ?' },
        { tag: '04 · Relance', title: 'Suivi', desc: "Rappeler la suite sans alourdir l'échange.", example: 'Je reviens vers vous.' },
      ],
    }),
  },
  steps_2: {
    templateId: 'steps',
    className: 'slide s-process s-process--count-2',
    label: '10A Process · 2 étapes',
    html: processVariantHtml({
      title: 'Deux gestes clés',
      eyebrow: 'Méthode courte',
      steps: [
        { title: 'Écouter', desc: 'Laisser le client formuler le besoin réel.' },
        { title: 'Confirmer', desc: 'Reformuler la suite attendue avant de clôturer.' },
      ],
    }),
  },
  steps_3: {
    templateId: 'steps',
    className: 'slide s-process s-process--count-3',
    label: '10B Process · 3 étapes',
    html: processVariantHtml({
      title: 'Trois temps utiles',
      eyebrow: 'Méthode',
      steps: [
        { title: 'Clarifier', desc: "Identifier l'objet exact de la demande." },
        { title: 'Répondre', desc: 'Donner une information simple et exploitable.' },
        { title: 'Ancrer', desc: 'Vérifier que la suite est comprise.' },
      ],
    }),
  },
  steps_4: {
    templateId: 'steps',
    className: 'slide s-process s-process--count-4',
    label: '10C Process · 4 étapes',
    html: processVariantHtml({
      title: 'Quatre étapes métier',
      eyebrow: 'Méthode complète',
      steps: [
        { title: 'Observer', desc: 'Regarder la situation réelle avant de décider.' },
        { title: 'Clarifier', desc: "Identifier l'information qui manque encore." },
        { title: 'Agir', desc: 'Donner une réponse simple et directement exploitable.' },
        { title: 'Confirmer', desc: 'Vérifier que la suite est claire pour tous.' },
      ],
    }),
  },
  recap_2: {
    templateId: 'recap',
    className: 'slide s-recap2',
    label: '11A Récap · 2 points',
    html: recapVariantHtml({
      title: "Deux réflexes à garder",
      points: [
        { title: 'Clarté avant vitesse', desc: 'Une réponse rapide reste inutile si le client ne comprend pas la suite.' },
        { title: 'Trace avant mémoire', desc: "Ce qui compte doit être formulé pour être retrouvé par l'équipe." },
      ],
    }),
  },
  recap_4: {
    templateId: 'recap',
    className: 'slide s-recap2',
    label: '11B Récap · 4 points',
    html: recapVariantHtml({
      title: "Quatre points à retenir",
      points: [
        { title: 'Accueillir', desc: 'Ouvrir avec une présence claire.' },
        { title: 'Qualifier', desc: 'Stabiliser la demande réelle.' },
        { title: 'Répondre', desc: 'Donner une suite exploitable.' },
        { title: 'Tracer', desc: "Laisser une information partageable." },
      ],
    }),
  },
  situations_2: {
    templateId: 'situations',
    className: 'slide s-situ s-situ--count-2',
    label: '16A Situations · 2 cartes',
    html: situationsVariantHtml({
      title: 'Deux postures client',
      eyebrow: 'Adapter sa posture',
      items: [
        { title: 'Client pressé.', desc: "Aller vite, mais garder une phrase de cadrage." },
        { title: 'Client inquiet.', desc: "Rassurer d'abord, puis expliquer la suite." },
      ],
    }),
  },
  situations_4: {
    templateId: 'situations',
    className: 'slide s-situ s-situ--count-4',
    label: '16B Situations · 4 cartes',
    html: situationsVariantHtml({
      title: 'Quatre postures client',
      eyebrow: 'Adapter sa posture',
      items: [
        { title: 'Pressé.', desc: "Réduire l'introduction." },
        { title: 'Hésitant.', desc: 'Clarifier par questions.' },
        { title: 'Mécontent.', desc: "Reconnaître l'émotion." },
        { title: 'Perdu.', desc: 'Reposer le chemin.' },
      ],
    }),
  },
  flow_2: {
    templateId: 'flow',
    className: 'slide s-flow s-flow--count-2',
    label: '17A Traiter une demande · 2 gestes',
    html: flowVariantHtml({
      title: 'Traiter une demande.',
      eyebrow: 'Flux court',
      steps: [
        { title: 'Comprendre', desc: 'Identifier précisément ce que la personne attend.' },
        { title: 'Confirmer', desc: 'Formuler la réponse ou la prochaine étape sans ambiguïté.' },
      ],
    }),
  },
  flow_3: {
    templateId: 'flow',
    className: 'slide s-flow s-flow--count-3',
    label: '17B Traiter une demande · 3 gestes',
    html: flowVariantHtml({
      title: 'Traiter une demande.',
      eyebrow: 'Flux en trois temps',
      steps: [
        { title: 'Identifier', desc: 'Repérer le besoin exprimé et le contexte utile.' },
        { title: 'Qualifier', desc: 'Vérifier la contrainte qui change la réponse.' },
        { title: 'Répondre', desc: 'Donner une suite claire, exploitable et traçable.' },
      ],
    }),
  },
  flow_4: {
    templateId: 'flow',
    className: 'slide s-flow s-flow--count-4',
    label: '17C Traiter une demande · 4 gestes',
    html: flowVariantHtml({
      title: 'Traiter une demande.',
      eyebrow: 'Flux en quatre temps',
      steps: [
        { title: 'Identifier', desc: 'Comprendre le besoin exprimé.' },
        { title: 'Qualifier', desc: 'Vérifier les contraintes utiles.' },
        { title: 'Agir', desc: 'Proposer une réponse concrète.' },
        { title: 'Clore', desc: 'Confirmer la suite avec précision.' },
      ],
    }),
  },
};

export const SOURCE_SLIDE_CATALOG = {
  ...SOURCE_SLIDES,
  ...SOURCE_SLIDE_VARIANTS,
};

export const SOURCE_SLIDE_INDEX = Object.entries(SOURCE_SLIDE_CATALOG).map(([id, slide]) => ({
  id,
  label: slide.label,
  templateId: slide.templateId || id,
  isVariant: Boolean(slide.templateId),
}));

const useSourceSlideScale = () => {
  const ref = useRef(null);
  const [scale, setScale] = useState(0.625);

  useLayoutEffect(() => {
    if (!ref.current) return undefined;
    const update = () => {
      const width = ref.current?.clientWidth || 1200;
      setScale(width / 1920);
    };
    update();
    const observer = new ResizeObserver(update);
    observer.observe(ref.current);
    return () => observer.disconnect();
  }, []);

  return [ref, scale];
};

// `replacements` : remplacements littéraux { "texte source": "texte affiché" }
// appliqués au HTML statique (ex : durée réelle de la pause).
export const SalesHackingSourceSlide = ({ sourceId, replacements }) => {
  const source = SOURCE_SLIDE_CATALOG[sourceId] || SOURCE_SLIDES.welcome;
  const [shellRef, scale] = useSourceSlideScale();

  let html = source.html;
  if (replacements) {
    for (const [from, to] of Object.entries(replacements)) {
      html = html.split(from).join(to);
    }
  }

  return (
    <div className="sales-source-deck-shell" ref={shellRef}>
      <section
        className={source.className}
        data-screen-label={source.label}
        style={{ transform: `scale(${scale})` }}
        dangerouslySetInnerHTML={{ __html: html }}
      />
    </div>
  );
};

export default SalesHackingSourceSlide;
