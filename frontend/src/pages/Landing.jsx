import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  ArrowRight,
  AudioLines,
  BookOpenCheck,
  CalendarClock,
  Check,
  ChevronDown,
  CircleCheck,
  Clock3,
  FileCheck2,
  FileStack,
  GraduationCap,
  Headphones,
  Layers3,
  LockKeyhole,
  Menu,
  MessageSquareText,
  Play,
  RadioTower,
  ShieldCheck,
  Sparkles,
  UsersRound,
  WandSparkles,
  X,
} from 'lucide-react'
import CadrenzaLogo from '../components/CadrenzaLogo.jsx'
import './Landing.css'

const AGENTS = [
  {
    id: 'referentiel',
    label: 'Référentiel',
    title: 'Analyse du référentiel',
    icon: BookOpenCheck,
    prompt: 'Analyse le REAC Employé commercial et construis le socle du parcours.',
    reply: 'Le référentiel est structuré en activités, compétences et critères. Chaque élément reste relié à sa source.',
    tasks: ['Repère les compétences attendues', 'Conserve chaque source', 'Prépare la base de connaissances'],
    artifact: 'Socle pédagogique · v1.4',
  },
  {
    id: 'pedagogie',
    label: 'Pédagogie',
    title: 'Construction pédagogique',
    icon: Layers3,
    prompt: 'Construis une séquence de 45 minutes sur la prise en charge client.',
    reply: 'La séance est découpée en objectifs, exemples métier, transitions et points de contrôle.',
    tasks: ['Structure les séquences', 'Rédige depuis le socle', 'Versionne chaque production'],
    artifact: 'Séquence 03 · prête à relire',
  },
  {
    id: 'audio',
    label: 'Audio',
    title: 'Production audio',
    icon: AudioLines,
    prompt: 'Prépare la voix et les repères de diffusion de cette séquence.',
    reply: 'Le script, les fichiers audio et la chronologie des slides ont été alignés.',
    tasks: ['Contrôle les scripts', 'Produit les fichiers audio', 'Synchronise voix et supports'],
    artifact: 'Audio 03 · 42 min 18 s',
  },
  {
    id: 'classe',
    label: 'Classe',
    title: 'Pilotage de la classe',
    icon: RadioTower,
    prompt: 'Programme cette séance à 9 h pour la promotion de septembre.',
    reply: 'La playlist, les accès et le Q&A contextuel sont prêts pour le créneau planifié.',
    tasks: ['Diffuse à heure fixe', 'Gère les accès', 'Conserve le contexte du Q&A'],
    artifact: 'Classe · lundi 09:00',
  },
]

const CAPABILITIES = [
  { label: 'Référentiel source', icon: <BookOpenCheck size={18} /> },
  { label: 'Base versionnée', icon: <Layers3 size={18} /> },
  { label: 'Cours structurés', icon: <FileStack size={18} /> },
  { label: 'Audio synchronisé', icon: <AudioLines size={18} /> },
  { label: 'Classe planifiée', icon: <CalendarClock size={18} /> },
  { label: 'Q&A contextuel', icon: <MessageSquareText size={18} /> },
  { label: 'Suivi par promotion', icon: <UsersRound size={18} /> },
  { label: 'Journaux exportables', icon: <FileCheck2 size={18} /> },
]

const FAQS = [
  {
    question: 'Cadrenza est-il un catalogue de cours à la demande ?',
    answer: 'Non. Cadrenza est conçu pour des classes planifiées, avec une heure de début, une playlist horodatée et un suivi distinct pour chaque promotion.',
  },
  {
    question: 'Faut-il reconstruire le cours pour chaque promotion ?',
    answer: 'Non. Le module reste attaché au titre professionnel. Il peut être repris par plusieurs promotions, avec des calendriers, accès et journaux séparés.',
  },
  {
    question: 'Le centre garde-t-il la main sur la production ?',
    answer: 'Oui. Les sources, versions, fichiers, horaires et états de verrouillage restent pilotés depuis l’espace centre.',
  },
  {
    question: 'Les agents travaillent-ils sans contrôle ?',
    answer: 'Chaque agent intervient sur une étape définie et produit une sortie relisible. L’équipe centre conserve le contrôle avant toute diffusion.',
  },
]

function PrimaryButton({ children, onClick, href, className = '' }) {
  const content = <>{children}<ArrowRight size={17} aria-hidden="true" /></>
  if (href) return <a className={`landing-button landing-button--primary ${className}`} href={href}>{content}</a>
  return <button className={`landing-button landing-button--primary ${className}`} type="button" onClick={onClick}>{content}</button>
}

function ProductPreview() {
  return (
    <div className="product-preview" aria-label="Aperçu du tableau de bord Cadrenza">
      <div className="product-preview__bar">
        <span className="window-dots" aria-hidden="true"><i /><i /><i /></span>
        <span>cadrenza.app / parcours</span>
        <span className="product-preview__secure"><LockKeyhole size={13} /> Espace centre</span>
      </div>
      <div className="product-preview__app">
        <aside className="product-preview__rail" aria-hidden="true">
          <CadrenzaLogo compact />
          <span className="is-active" /><span /><span /><span />
          <i />
        </aside>
        <div className="product-preview__main">
          <div className="product-preview__heading">
            <div>
              <small>TP Employé commercial</small>
              <strong>Production du module</strong>
            </div>
            <span><CircleCheck size={15} /> Socle validé</span>
          </div>
          <div className="product-preview__progress" aria-label="Progression du module">
            <div><span>Référentiel</span><i className="is-done" /></div>
            <div><span>Base</span><i className="is-done" /></div>
            <div><span>Cours</span><i className="is-current" /></div>
            <div><span>Audio</span><i /></div>
            <div><span>Classe</span><i /></div>
          </div>
          <div className="product-preview__grid">
            <section className="preview-module-card">
              <div className="preview-module-card__top">
                <span className="preview-module-card__icon"><FileStack size={19} /></span>
                <div><small>Module 03</small><strong>Conseiller le client</strong></div>
                <span className="preview-status">En production</span>
              </div>
              <div className="preview-module-card__rows">
                <span><Check size={13} /> Objectifs pédagogiques <b>6</b></span>
                <span><Check size={13} /> Séquences structurées <b>4</b></span>
                <span><Clock3 size={13} /> Durée estimée <b>3 h 20</b></span>
              </div>
            </section>
            <section className="preview-activity-card">
              <small>Activité des agents</small>
              <div><span><BookOpenCheck size={14} /></span><p><strong>Référentiel analysé</strong><small>Il y a 2 min</small></p></div>
              <div><span><Layers3 size={14} /></span><p><strong>Séquence 03 générée</strong><small>En relecture</small></p></div>
              <div><span><AudioLines size={14} /></span><p><strong>Script audio préparé</strong><small>En attente</small></p></div>
            </section>
          </div>
        </div>
      </div>
      <span className="product-preview__play" aria-hidden="true"><Play size={20} fill="currentColor" /></span>
    </div>
  )
}

function AgentWorkbench({ agent }) {
  const AgentIcon = agent.icon
  return (
    <div className="agent-stage" role="tabpanel" id="agent-panel" aria-labelledby={`agent-tab-${agent.id}`}>
      <div className="agent-stage__ghost agent-stage__ghost--left" aria-hidden="true" />
      <div className="agent-stage__ghost agent-stage__ghost--right" aria-hidden="true" />
      <div className="agent-workbench">
        <div className="agent-workbench__conversation">
          <div className="agent-workbench__bar"><span className="window-dots"><i /><i /><i /></span><small>Mission en cours</small></div>
          <div className="agent-message agent-message--request">{agent.prompt}</div>
          <div className="agent-message agent-message--reply">
            <span><AgentIcon size={17} /></span>
            <p>{agent.reply}</p>
          </div>
          <div className="agent-artifact"><FileCheck2 size={15} /><span>{agent.artifact}</span><Check size={15} /></div>
        </div>
        <div className="agent-workbench__detail" aria-live="polite">
          <span className="agent-workbench__icon"><AgentIcon size={28} /></span>
          <small>Agent logiciel</small>
          <h3>{agent.title}</h3>
          <ul>{agent.tasks.map((task) => <li key={task}><Check size={15} />{task}</li>)}</ul>
          <p>Sa sortie reste disponible pour relecture, version et reprise.</p>
        </div>
      </div>
    </div>
  )
}

function CenterPreview() {
  return (
    <div className="center-preview" aria-label="Aperçu du pilotage d’une promotion">
      <div className="center-preview__top">
        <span className="window-dots"><i /><i /><i /></span>
        <small>Centre Horizon</small>
        <span><ShieldCheck size={14} /> Session opérateur</span>
      </div>
      <div className="center-preview__body">
        <div className="center-preview__title"><div><small>Promotions</small><strong>Employé commercial</strong></div><button type="button">Nouvelle promotion</button></div>
        <div className="promotion-card is-live"><span>En cours</span><div><strong>Promotion Septembre</strong><small>Lun. à ven. · 09:00</small></div><b>18 apprenants</b></div>
        <div className="promotion-card"><span>Planifiée</span><div><strong>Promotion Novembre</strong><small>Module déjà produit</small></div><b>14 apprenants</b></div>
        <div className="center-preview__foot"><span><Check size={13} /> Audio verrouillé</span><span>Journaux exportables</span></div>
      </div>
    </div>
  )
}

function ClassPreview() {
  return (
    <div className="class-preview" aria-label="Aperçu de la classe apprenant">
      <div className="class-preview__top"><CadrenzaLogo compact /><div><small>TP Employé commercial</small><strong>La relation client en magasin</strong></div><span><RadioTower size={13} /> En direct</span></div>
      <div className="class-preview__slide"><small>Notion clé</small><h3>Une écoute active produit des informations exploitables.</h3><div className="class-preview__wave" aria-hidden="true">{Array.from({ length: 26 }, (_, index) => <i key={index} style={{ height: `${18 + ((index * 19) % 54)}%` }} />)}</div></div>
      <div className="class-preview__control"><span><Headphones size={15} /> 09:42</span><div><i /><i /><i /></div><button type="button">Poser une question</button></div>
    </div>
  )
}

export default function Landing() {
  const navigate = useNavigate()
  const platformId = new URLSearchParams(window.location.search).get('p')
  const studentCourseHref = platformId ? `/cours?p=${encodeURIComponent(platformId)}` : '/cours'
  const [mobileOpen, setMobileOpen] = useState(false)
  const [scrolled, setScrolled] = useState(false)
  const [activeAgent, setActiveAgent] = useState(AGENTS[0])

  useEffect(() => {
    const handleScroll = () => setScrolled(window.scrollY > 16)
    handleScroll()
    window.addEventListener('scroll', handleScroll, { passive: true })
    return () => window.removeEventListener('scroll', handleScroll)
  }, [])

  useEffect(() => {
    const closeOnEscape = (event) => event.key === 'Escape' && setMobileOpen(false)
    document.addEventListener('keydown', closeOnEscape)
    document.body.style.overflow = mobileOpen ? 'hidden' : ''
    return () => {
      document.removeEventListener('keydown', closeOnEscape)
      document.body.style.overflow = ''
    }
  }, [mobileOpen])

  const handleAgentKeyDown = (event, agentId) => {
    const currentIndex = AGENTS.findIndex((agent) => agent.id === agentId)
    let nextIndex = currentIndex
    if (event.key === 'ArrowRight') nextIndex = (currentIndex + 1) % AGENTS.length
    else if (event.key === 'ArrowLeft') nextIndex = (currentIndex - 1 + AGENTS.length) % AGENTS.length
    else if (event.key === 'Home') nextIndex = 0
    else if (event.key === 'End') nextIndex = AGENTS.length - 1
    else return
    event.preventDefault()
    const nextAgent = AGENTS[nextIndex]
    setActiveAgent(nextAgent)
    requestAnimationFrame(() => document.getElementById(`agent-tab-${nextAgent.id}`)?.focus())
  }

  const openSignup = () => navigate('/connexion-centre?mode=signup')
  const closeMenu = () => setMobileOpen(false)

  return (
    <div className="cadrenza-landing">
      <a className="landing-skip" href="#contenu">Aller au contenu</a>

      <header className={`landing-header ${scrolled ? 'is-scrolled' : ''}`}>
        <div className="landing-announcement">
          <span><Sparkles size={14} /> Une plateforme pour produire, planifier et diffuser vos parcours RNCP</span>
          <a href={studentCourseHref}>Accès apprenant <ArrowRight size={14} /></a>
        </div>
        <nav className="landing-nav" aria-label="Navigation principale">
          <a href="#accueil" className="landing-nav__brand" onClick={closeMenu}><CadrenzaLogo /></a>
          <div className="landing-nav__links">
            <a href="#methode">La méthode</a>
            <a href="#agents">Les agents</a>
            <a href="#experience">L’expérience</a>
            <a href="#faq">FAQ</a>
          </div>
          <div className="landing-nav__actions">
            <button type="button" className="landing-button landing-button--quiet" onClick={() => navigate('/connexion-centre')}>Se connecter</button>
            <PrimaryButton href="#demo">Voir la démo</PrimaryButton>
          </div>
          <button className="landing-nav__menu" type="button" aria-label={mobileOpen ? 'Fermer le menu' : 'Ouvrir le menu'} aria-expanded={mobileOpen} aria-controls="landing-mobile-nav" onClick={() => setMobileOpen((open) => !open)}>{mobileOpen ? <X /> : <Menu />}</button>
        </nav>
        {mobileOpen && <div className="landing-mobile-nav" id="landing-mobile-nav">
          <a href="#methode" onClick={closeMenu}>La méthode</a><a href="#agents" onClick={closeMenu}>Les agents</a><a href="#experience" onClick={closeMenu}>L’expérience</a><a href="#faq" onClick={closeMenu}>FAQ</a><a href={studentCourseHref} onClick={closeMenu}>Accès apprenant</a>
          <button type="button" onClick={() => navigate('/connexion-centre')}>Se connecter</button><button className="is-primary" type="button" onClick={openSignup}>Créer un espace centre</button>
        </div>}
      </header>

      <main id="contenu">
        <section className="landing-hero" id="accueil">
          <div className="landing-hero__aura" aria-hidden="true" />
          <div className="landing-hero__dots" aria-hidden="true" />
          <div className="landing-hero__content">
            <div className="landing-proof-chip"><ShieldCheck size={16} /><span>Cadre RNCP conservé</span><i /><strong>Production traçable</strong></div>
            <h1>Des agents pédagogiques autonomes au service de vos parcours RNCP.</h1>
            <p className="landing-hero__lead">Transformez un référentiel en module audio synchronisé, puis diffusez-le à chaque promotion au créneau prévu.</p>
            <div className="landing-command" role="group" aria-label="Découvrir le parcours Cadrenza">
              <div className="landing-command__prompt"><WandSparkles size={21} /><span>Prépare le module TP Employé commercial à partir du REAC</span></div>
              <div className="landing-command__footer"><span><GraduationCap size={17} /> Parcours RNCP</span><div><PrimaryButton href="#demo">Découvrir le parcours</PrimaryButton><button className="landing-button landing-button--secondary" type="button" onClick={() => navigate('/connexion-centre')}>Accéder à l’espace centre</button></div></div>
            </div>
            <div className="landing-proof-strip" aria-label="Principales garanties du produit"><span>Une source</span><i /><span>Un module durable</span><i /><span>Plusieurs promotions</span><i /><span>Une trace complète</span></div>
          </div>
          <div className="landing-hero__preview" id="demo"><ProductPreview /></div>
        </section>

        <section className="landing-section method" id="methode">
          <div className="section-heading">
            <span className="section-kicker">Une chaîne continue</span>
            <h2>Du référentiel à la classe, sans rupture.</h2>
            <p>Chaque agent prend en charge une étape précise. La sortie reste visible, contrôlable et prête pour l’étape suivante.</p>
          </div>
          <div className="method-flow">
            {[
              { icon: <FileCheck2 size={22} />, number: '01', title: 'Référentiel', text: 'Le REAC reste la source de travail.' },
              { icon: <Layers3 size={22} />, number: '02', title: 'Base durable', text: 'Les connaissances sont organisées et versionnées.' },
              { icon: <Headphones size={22} />, number: '03', title: 'Cours et audio', text: 'Le contenu, les slides et la voix avancent ensemble.' },
              { icon: <CalendarClock size={22} />, number: '04', title: 'Classe planifiée', text: 'Chaque promotion rejoint le module au créneau prévu.' },
            ].map(({ icon, number, title, text }, index) => <article key={title}><span className="method-flow__number">{number}</span><span className="method-flow__icon">{icon}</span><h3>{title}</h3><p>{text}</p>{index < 3 && <ArrowRight className="method-flow__arrow" size={18} aria-hidden="true" />}</article>)}
          </div>
        </section>

        <section className="capability-band" aria-label="Fonctionnalités de Cadrenza">
          <div className="capability-band__track">{[...CAPABILITIES, ...CAPABILITIES].map(({ label, icon }, index) => <span key={`${label}-${index}`} aria-hidden={index >= CAPABILITIES.length ? 'true' : undefined}>{icon}{label}</span>)}</div>
        </section>

        <section className="landing-section agents" id="agents">
          <div className="section-heading">
            <span className="section-kicker">Des agents spécialisés</span>
            <h2>Un rôle clair. Un livrable précis.</h2>
            <p>Pas de personnage décoratif. Chaque agent correspond à une fonction logicielle et à un artefact vérifiable.</p>
          </div>
          <div className="agent-tabs" role="tablist" aria-label="Agents de production">{AGENTS.map((agent) => {
            const Icon = agent.icon
            const selected = activeAgent.id === agent.id
            return <button key={agent.id} id={`agent-tab-${agent.id}`} type="button" role="tab" aria-selected={selected} aria-controls="agent-panel" tabIndex={selected ? 0 : -1} className={selected ? 'is-active' : ''} onClick={() => setActiveAgent(agent)} onKeyDown={(event) => handleAgentKeyDown(event, agent.id)}><span><Icon size={17} /></span>{agent.label}</button>
          })}</div>
          <AgentWorkbench agent={activeAgent} />
        </section>

        <section className="landing-section experience" id="experience">
          <div className="experience-grid">
            <CenterPreview />
            <div className="experience-copy">
              <span className="section-kicker">Le centre pilote</span>
              <h2>Produisez une fois. Planifiez chaque promotion.</h2>
              <p>Le tableau de bord rassemble le pipeline, les horaires, les accès, les audios et les exports de suivi.</p>
              <ul><li><Check size={16} />Promotions et accès séparés</li><li><Check size={16} />Audio verrouillé avant diffusion</li><li><Check size={16} />Présences et journaux exportables</li></ul>
              <PrimaryButton href="#contact">Voir le fonctionnement</PrimaryButton>
            </div>
          </div>
          <div className="experience-grid experience-grid--reverse">
            <ClassPreview />
            <div className="experience-copy">
              <span className="section-kicker">L’apprenant rejoint</span>
              <h2>Une classe lisible, à l’heure prévue.</h2>
              <p>La playlist suit le créneau défini. Les slides et le Q&A restent liés au passage réellement enseigné.</p>
              <ul><li><Check size={16} />Accès par promotion ou invitation</li><li><Check size={16} />Audio et supports synchronisés</li><li><Check size={16} />Questions reliées au contexte du cours</li></ul>
              <a className="landing-text-link" href={studentCourseHref}>Découvrir l’accès apprenant <ArrowRight size={16} /></a>
            </div>
          </div>
        </section>

        <section className="landing-section setup">
          <div className="setup-copy"><span className="section-kicker">Mise en route</span><h2>Votre premier module en trois étapes.</h2><p>Cadrenza guide l’équipe centre depuis le dépôt du référentiel jusqu’à la première classe planifiée.</p><PrimaryButton onClick={openSignup}>Créer un espace centre</PrimaryButton></div>
          <ol className="setup-steps">
            <li><span>01</span><div><strong>Ajoutez le référentiel</strong><p>Déposez le REAC et contrôlez les sources reconnues.</p></div><FileCheck2 size={20} /></li>
            <li><span>02</span><div><strong>Validez le module</strong><p>Relisez le cours, les supports et les fichiers audio.</p></div><CircleCheck size={20} /></li>
            <li><span>03</span><div><strong>Planifiez la promotion</strong><p>Définissez les horaires, les accès et la diffusion.</p></div><CalendarClock size={20} /></li>
          </ol>
        </section>

        <section className="landing-section faq" id="faq">
          <div className="section-heading"><span className="section-kicker">Questions fréquentes</span><h2>Le cadre avant l’automatisation.</h2><p>Cadrenza automatise la production et la diffusion sans masquer les sources, les étapes ni les responsabilités.</p></div>
          <div className="faq-list">{FAQS.map(({ question, answer }, index) => <details key={question} open={index === 0}><summary>{question}<ChevronDown size={18} /></summary><p>{answer}</p></details>)}</div>
        </section>

        <section className="landing-cta" id="contact">
          <div className="landing-cta__aura" aria-hidden="true" />
          <div className="landing-cta__content"><CadrenzaLogo compact /><span>Votre premier titre professionnel</span><h2>Préparez le module. Cadencez les promotions.</h2><p>Un même socle pédagogique, plusieurs classes, une trace complète.</p><div><PrimaryButton onClick={openSignup}>Créer un espace centre</PrimaryButton><button className="landing-button landing-button--secondary" type="button" onClick={() => navigate('/connexion-centre')}>Se connecter</button></div></div>
        </section>
      </main>

      <footer className="landing-footer">
        <div className="landing-footer__top"><div><CadrenzaLogo /><p>Production et diffusion synchrone de parcours RNCP pour les centres de formation.</p></div><nav aria-label="Navigation de pied de page"><div><strong>Découvrir</strong><a href="#methode">La méthode</a><a href="#agents">Les agents</a><a href="#experience">L’expérience</a></div><div><strong>Accès</strong><a href="/connexion-centre">Espace centre</a><a href={studentCourseHref}>Espace apprenant</a></div><div><strong>Produit</strong><span>Modules RNCP</span><span>Classes synchrones</span><span>Suivi multi-promotion</span></div></nav></div>
        <div className="landing-footer__bottom"><span>© 2026 Cadrenza. Tous droits réservés.</span><span>Conçu pour les parcours RNCP synchrones.</span></div>
      </footer>
    </div>
  )
}
