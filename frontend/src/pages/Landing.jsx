import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  ArrowRight,
  Bot,
  CalendarClock,
  Check,
  Clock3,
  FileCheck2,
  FileStack,
  GraduationCap,
  Headphones,
  Layers3,
  LockKeyhole,
  Menu,
  Play,
  RadioTower,
  ShieldCheck,
  UsersRound,
  Volume2,
  X,
} from 'lucide-react'
import CadrenzaLogo from '../components/CadrenzaLogo.jsx'
import './Landing.css'

const DEFAULT_TRAINING_BRIEF = "Crée-moi une formation où un professeur IA va dispenser les cours du titre professionnel Conseiller relation client à distance (RNCP42431). Cette formation s'étend sur deux mois, à raison de deux jours par semaine, le lundi et le jeudi."

const AGENTS = [
  {
    id: 'referentiel',
    label: 'Référentiel',
    name: 'Analyse du référentiel',
    robot: '/robot-blue.png',
    tone: 'blue',
    prompt: 'Analyse le REAC du titre Employé commercial et structure le socle du parcours.',
    reply: 'Les activités types, compétences et critères ont été reliés à une trame pédagogique vérifiable.',
    tasks: ['Repère les compétences attendues', 'Conserve le lien avec la source', 'Prépare la base de connaissances'],
  },
  {
    id: 'pedagogie',
    label: 'Pédagogie',
    name: 'Construction pédagogique',
    robot: '/robot-violet.png',
    tone: 'violet',
    prompt: 'Construis les séquences du module sans diluer les exigences du titre.',
    reply: 'Le déroulé est découpé en séances, avec objectifs, exemples métier, transitions et points de contrôle.',
    tasks: ['Rédige les cours à partir du socle', 'Découpe les séances au bon rythme', 'Versionne chaque production'],
  },
  {
    id: 'audio',
    label: 'Audio',
    name: 'Production audio',
    robot: '/robot-amber.png',
    tone: 'amber',
    prompt: 'Prépare une voix de cours stable et les repères nécessaires à la diffusion synchronisée.',
    reply: 'Les scripts ont été contrôlés puis associés à des fichiers audio et à leur chronologie de lecture.',
    tasks: ['Prépare les scripts pour la voix', 'Produit les fichiers du module', 'Aligne audio, slides et repères'],
  },
  {
    id: 'classe',
    label: 'Classe',
    name: 'Pilotage de la classe',
    robot: '/robot-green.png',
    tone: 'green',
    prompt: 'Ouvre la séance à 9 h pour la promotion de septembre et garde le contexte du cours disponible.',
    reply: 'La playlist horodatée, les accès et le Q&A contextuel sont prêts pour le créneau planifié.',
    tasks: ['Diffuse le cours à heure fixe', 'Gère les accès de la promotion', 'Conserve le contexte pour le Q&A'],
  },
]

const PIPELINE_STEPS = [
  { title: 'Référentiel', text: 'Le REAC reste la source de travail.', icon: <FileCheck2 size={24} /> },
  { title: 'Base durable', text: 'Les connaissances sont organisées et réutilisables.', icon: <Layers3 size={24} /> },
  { title: 'Cours et audio', text: 'Le contenu, les slides et la voix sont produits ensemble.', icon: <Headphones size={24} /> },
  { title: 'Classe planifiée', text: 'Chaque promotion rejoint le même module au créneau prévu.', icon: <CalendarClock size={24} /> },
]

function VideoPlaceholder({ number, title, description, compact = false }) {
  return (
    <figure className={`video-slot ${compact ? 'video-slot--compact' : ''}`}>
      <div className="video-slot__frame" role="img" aria-label={`Emplacement pour la vidéo : ${title}`}>
        <div className="video-slot__browser">
          <span />
          <span />
          <span />
          <p>Vidéo {number}</p>
        </div>
        <div className="video-slot__center">
          <span className="video-slot__play" aria-hidden="true">
            <Play size={compact ? 22 : 28} fill="currentColor" />
          </span>
          <strong>Emplacement vidéo</strong>
          <small>Format 16:9, son désactivé au démarrage</small>
        </div>
        <div className="video-slot__timeline" aria-hidden="true">
          <span />
          <i />
          <em>00:00</em>
        </div>
      </div>
      <figcaption>
        <span>Vidéo {number}</span>
        <div>
          <h3>{title}</h3>
          <p>{description}</p>
        </div>
      </figcaption>
    </figure>
  )
}

function CenterDashboardPreview() {
  return (
    <div className="surface-preview surface-preview--center" role="group" aria-label="Aperçu du pilotage centre">
      <div className="surface-preview__topbar">
        <CadrenzaLogo compact />
        <span>Centre Horizon</span>
        <i>Session opérateur</i>
      </div>
      <div className="surface-preview__body">
        <aside aria-hidden="true">
          <span className="is-active" />
          <span />
          <span />
          <span />
        </aside>
        <div className="surface-preview__content">
          <div className="surface-preview__heading">
            <div>
              <small>Promotions</small>
              <strong>Employé commercial</strong>
            </div>
            <span className="surface-preview__action">Nouvelle promotion</span>
          </div>
          <div className="promotion-row">
            <span className="promotion-row__status">En cours</span>
            <div><strong>Promotion Septembre</strong><small>Lun. à ven. · 09:00</small></div>
            <b>18 apprenants</b>
          </div>
          <div className="promotion-row">
            <span className="promotion-row__status is-planned">Planifiée</span>
            <div><strong>Promotion Novembre</strong><small>Module déjà produit</small></div>
            <b>14 apprenants</b>
          </div>
          <div className="surface-preview__footerline">
            <span><Check size={14} /> Audio verrouillé</span>
            <span>Journaux exportables</span>
          </div>
        </div>
      </div>
    </div>
  )
}

function StudentClassPreview() {
  return (
    <div className="surface-preview surface-preview--student" role="group" aria-label="Aperçu de la classe apprenant">
      <div className="class-preview__header">
        <CadrenzaLogo compact />
        <div>
          <small>TP Employé commercial</small>
          <strong>La relation client en magasin</strong>
        </div>
        <span><RadioTower size={14} /> En direct</span>
      </div>
      <div className="class-preview__slide">
        <span>Notion clé</span>
        <h3>Une écoute active produit des informations exploitables.</h3>
        <div className="class-preview__wave" aria-hidden="true">
          {Array.from({ length: 28 }, (_, index) => <i key={index} style={{ height: `${18 + ((index * 17) % 48)}%` }} />)}
        </div>
      </div>
      <div className="class-preview__controls">
        <span><Volume2 size={17} /> 09:42</span>
        <div><i /><i /><i /></div>
        <span className="surface-preview__action">Poser une question</span>
      </div>
    </div>
  )
}

export default function Landing() {
  const navigate = useNavigate()
  const [mobileOpen, setMobileOpen] = useState(false)
  const [scrolled, setScrolled] = useState(false)
  const [activeAgent, setActiveAgent] = useState(AGENTS[0])
  const [trainingBrief, setTrainingBrief] = useState(DEFAULT_TRAINING_BRIEF)

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

  useEffect(() => {
    const handleScroll = () => setScrolled(window.scrollY > 18)
    handleScroll()
    window.addEventListener('scroll', handleScroll, { passive: true })
    return () => window.removeEventListener('scroll', handleScroll)
  }, [])

  useEffect(() => {
    const handleKeyDown = (event) => {
      if (event.key === 'Escape') setMobileOpen(false)
    }
    document.addEventListener('keydown', handleKeyDown)
    document.body.style.overflow = mobileOpen ? 'hidden' : ''
    return () => {
      document.removeEventListener('keydown', handleKeyDown)
      document.body.style.overflow = ''
    }
  }, [mobileOpen])

  const closeMenu = () => setMobileOpen(false)

  const handleTrainingBriefSubmit = (event) => {
    event.preventDefault()
    window.sessionStorage.setItem('cadrenza-training-brief', trainingBrief.trim())
    navigate('/connexion-centre?mode=signup')
  }

  return (
    <div className="cadrenza-site">
      <a className="skip-link" href="#contenu">Aller au contenu</a>

      <header className={`site-header ${scrolled ? 'site-header--scrolled' : ''}`}>
        <div className="announcement-bar">
          <span><RadioTower size={14} /> Plateforme conçue pour les centres de formation RNCP</span>
          <a href="/cours">Accès apprenant <ArrowRight size={14} /></a>
        </div>
        <nav className="site-nav" aria-label="Navigation principale">
          <a className="site-nav__brand" href="#accueil" onClick={closeMenu}>
            <CadrenzaLogo />
          </a>

          <div className="site-nav__links">
            <a href="#methode">La méthode</a>
            <a href="#agents">Les robots</a>
            <a href="#experience">La classe</a>
            <a href="#pilotage">Le pilotage</a>
          </div>

          <div className="site-nav__actions">
            <button type="button" className="button button--quiet" onClick={() => navigate('/connexion-centre')}>
              Connexion
            </button>
            <a className="button button--signal" href="#demo">
              Voir la démo
            </a>
          </div>

          <button
            type="button"
            className="site-nav__menu"
            aria-label={mobileOpen ? 'Fermer le menu' : 'Ouvrir le menu'}
            aria-controls="mobile-navigation"
            aria-expanded={mobileOpen}
            onClick={() => setMobileOpen((open) => !open)}
          >
            {mobileOpen ? <X /> : <Menu />}
          </button>
        </nav>

        {mobileOpen && (
          <div id="mobile-navigation" className="mobile-nav mobile-nav--open">
            <a href="#methode" onClick={closeMenu}>La méthode</a>
            <a href="#agents" onClick={closeMenu}>Les robots</a>
            <a href="#experience" onClick={closeMenu}>La classe</a>
            <a href="#pilotage" onClick={closeMenu}>Le pilotage</a>
            <a href="/cours" onClick={closeMenu}>Accès apprenant</a>
            <button type="button" onClick={() => navigate('/connexion-centre')}>Connexion centre</button>
            <button type="button" className="button--signal" onClick={() => navigate('/connexion-centre?mode=signup')}>
              Créer un espace centre
            </button>
          </div>
        )}
      </header>

      <main id="contenu">
        <section className="command-hero" id="accueil">
          <div className="command-hero__mesh" aria-hidden="true" />
          <div className="command-hero__inner">
            <div className="command-hero__signal">
              <span><Bot size={15} /> Professeurs logiciels spécialisés</span>
              <i />
              <span>Cadre RNCP conservé</span>
            </div>

            <h1>
              Des professeurs IA{' '}
              <span className="command-hero__robot" aria-hidden="true">
                <img src="/robot-blue.png" alt="" width="96" height="96" />
              </span>{' '}
              autonomes pour délivrer vos formations.
            </h1>
            <p className="command-hero__lead">
              Décrivez le titre professionnel, le rythme et la durée. Cadrenza prépare le parcours, ses cours et son calendrier.
            </p>

            <form className="brief-composer" onSubmit={handleTrainingBriefSubmit}>
              <label className="brief-composer__label" htmlFor="training-brief">
                Décrivez la formation à créer
              </label>
              <div className="brief-composer__field">
                <FileStack size={20} aria-hidden="true" />
                <textarea
                  id="training-brief"
                  value={trainingBrief}
                  onChange={(event) => setTrainingBrief(event.target.value)}
                  rows={4}
                  spellCheck="true"
                />
              </div>
              <div className="brief-composer__footer">
                <div className="brief-composer__teacher">
                  <span><Bot size={17} /> Professeur IA</span>
                  <small>Référentiel, cours, audio et planning</small>
                </div>
                <div className="brief-composer__actions">
                  <a className="button button--composer-secondary" href="#demo">Voir une démo</a>
                  <button className="button button--signal" type="submit" disabled={!trainingBrief.trim()}>
                    Créer cette formation <ArrowRight size={17} />
                  </button>
                </div>
              </div>
            </form>

            <div className="command-hero__details" aria-label="Éléments générés par Cadrenza">
              <span><Check size={15} /> Référentiel RNCP</span>
              <span><Check size={15} /> Cours et audio</span>
              <span><Check size={15} /> Calendrier synchrone</span>
            </div>
          </div>
        </section>

        <section className="hero hero--fleet" id="professeurs">
          <div className="hero__grid" aria-hidden="true" />
          <img
            className="hero__art"
            src="/cadrenza-robot-fleet.webp"
            alt="Quatre robots logiciels coordonnent la préparation et la diffusion d'un module de formation"
            width="1536"
            height="1024"
            loading="lazy"
          />
          <div className="hero__veil" aria-hidden="true" />

          <div className="hero__content">
            <h2>
              <span className="hero__line">Déployez une armée</span>{' '}
              <span className="hero__line">de professeurs <span className="hero__accent">IA</span></span>
            </h2>
            <p className="hero__lead">
              Cadrenza structure le référentiel, produit le cours et son audio, puis ouvre la classe aux apprenants à l'heure prévue.
            </p>
            <div className="hero__actions">
              <a className="button button--signal button--large" href="#demo">
                Découvrir le parcours <ArrowRight size={18} />
              </a>
              <button className="button button--outline button--large" type="button" onClick={() => navigate('/connexion-centre')}>
                Accéder à l'espace centre
              </button>
            </div>
            <div className="hero__assurance">
              <span><Check size={15} /> Référentiel conservé</span>
              <span><Check size={15} /> Modules versionnés</span>
              <span><Check size={15} /> Promotions séparées</span>
            </div>
          </div>
        </section>

        <section className="video-section section-shell" id="demo">
          <div className="section-intro section-intro--split">
            <div>
              <p className="section-label">Présentation</p>
              <h2>Montrez le produit avant de demander un rendez-vous.</h2>
            </div>
            <p>
              Cet emplacement est prêt pour votre vidéo principale. Le cadre prévoit un poster, des sous-titres et une lecture sans son automatique.
            </p>
          </div>
          <VideoPlaceholder
            number="01"
            title="Cadrenza en deux minutes"
            description="Du référentiel source jusqu'à la première classe planifiée."
          />
        </section>

        <section className="method-section section-shell" id="methode">
          <div className="section-intro">
            <p className="section-label">Le principe fondateur</p>
            <h2>Un module durable pour chaque titre professionnel.</h2>
            <p>
              L'équipe centre produit le socle une fois. Chaque promotion reçoit ensuite le même cadre pédagogique, avec son propre calendrier, ses accès et son suivi.
            </p>
          </div>

          <div className="durable-diagram">
            <div className="durable-diagram__source">
              <FileStack size={30} />
              <span>Source officielle</span>
              <strong>Référentiel RNCP</strong>
              <small>Activités, compétences, critères</small>
            </div>
            <div className="durable-diagram__flow" aria-hidden="true"><i /><ArrowRight /></div>
            <div className="durable-diagram__module">
              <span>Module durable</span>
              <strong>Cours, audio, slides, Q&A</strong>
              <div><i /><i /><i /><i /><i /></div>
            </div>
            <div className="durable-diagram__flow" aria-hidden="true"><i /><ArrowRight /></div>
            <div className="durable-diagram__promos">
              {['Septembre', 'Novembre', 'Février'].map((month, index) => (
                <div key={month}>
                  <span>Promotion</span>
                  <strong>{month}</strong>
                  <small>{index === 0 ? 'En cours' : 'Planifiée'}</small>
                </div>
              ))}
            </div>
          </div>

          <ol className="pipeline" aria-label="Étapes de production">
            {PIPELINE_STEPS.map(({ title, text, icon }, index) => (
              <li key={title}>
                <span className="pipeline__number">{String(index + 1).padStart(2, '0')}</span>
                {icon}
                <div><h3>{title}</h3><p>{text}</p></div>
              </li>
            ))}
          </ol>
        </section>

        <section className="agents-section" id="agents">
          <div className="section-shell">
            <div className="section-intro section-intro--on-dark">
              <p className="section-label">Une chaîne de robots spécialisés</p>
              <h2>Chaque robot produit un artefact précis.</h2>
              <p>Pas d'avatar humain ni de personnalité inventée. Chaque agent correspond à une fonction contrôlable de la chaîne pédagogique.</p>
            </div>

            <div className="agent-tabs" role="tablist" aria-label="Robots de production">
              {AGENTS.map((agent) => (
                <button
                  key={agent.id}
                  id={`agent-tab-${agent.id}`}
                  type="button"
                  role="tab"
                  aria-selected={activeAgent.id === agent.id}
                  aria-controls="agent-panel"
                  tabIndex={activeAgent.id === agent.id ? 0 : -1}
                  className={activeAgent.id === agent.id ? 'is-active' : ''}
                  onClick={() => setActiveAgent(agent)}
                  onKeyDown={(event) => handleAgentKeyDown(event, agent.id)}
                >
                  <img src={agent.robot} alt="" loading="lazy" />
                  <span>{agent.label}</span>
                </button>
              ))}
            </div>

            <div
              id="agent-panel"
              className={`agent-panel agent-panel--${activeAgent.tone}`}
              role="tabpanel"
              aria-labelledby={`agent-tab-${activeAgent.id}`}
            >
              <div className="agent-panel__conversation">
                <div className="conversation-bubble conversation-bubble--request">{activeAgent.prompt}</div>
                <div className="conversation-bubble conversation-bubble--reply">
                  <img src={activeAgent.robot} alt="" />
                  <p>{activeAgent.reply}</p>
                </div>
                <div className="conversation-artifact">
                  <span><FileCheck2 size={16} /> Artefact contrôlable</span>
                  <div><i /><i /><i /></div>
                </div>
              </div>
              <div className="agent-panel__detail" aria-live="polite">
                <img src={activeAgent.robot} alt="" />
                <div>
                  <span>Robot logiciel</span>
                  <h3>{activeAgent.name}</h3>
                </div>
                <ul>
                  {activeAgent.tasks.map((task) => <li key={task}><Check size={16} /> {task}</li>)}
                </ul>
                <p>La sortie reste disponible dans le pipeline pour relecture, version et reprise.</p>
              </div>
            </div>
          </div>
        </section>

        <section className="experience-section section-shell" id="experience">
          <div className="section-intro section-intro--split">
            <div>
              <p className="section-label">Deux expériences, un même module</p>
              <h2>Le centre pilote. L'apprenant rejoint une classe.</h2>
            </div>
            <p>
              Cadrenza sépare les tâches opérateur de l'expérience de cours. Les réglages restent au centre; la séance reste lisible pour l'apprenant.
            </p>
          </div>

          <div className="surface-story" id="pilotage">
            <div className="surface-story__copy">
              <span><ShieldCheck size={18} /> Vue centre</span>
              <h3>Produire, planifier et surveiller plusieurs promotions.</h3>
              <p>Le tableau de bord rassemble le pipeline, les horaires, les accès, les audios et les exports de suivi.</p>
              <ul>
                <li><Check size={16} /> Une séparation claire entre centres et promotions</li>
                <li><Check size={16} /> Verrouillage des audios avant diffusion</li>
                <li><Check size={16} /> Présences et journaux exportables</li>
              </ul>
            </div>
            <CenterDashboardPreview />
          </div>

          <div className="surface-story surface-story--reverse">
            <div className="surface-story__copy">
              <span><GraduationCap size={18} /> Vue apprenant</span>
              <h3>Entrer à l'heure dans une classe audio structurée.</h3>
              <p>La playlist suit le créneau prévu. Les slides et le Q&A restent liés au passage réellement enseigné.</p>
              <ul>
                <li><Check size={16} /> Accès par promotion ou invitation</li>
                <li><Check size={16} /> Audio et supports synchronisés</li>
                <li><Check size={16} /> Questions reliées au contexte du cours</li>
              </ul>
            </div>
            <StudentClassPreview />
          </div>
        </section>

        <section className="video-duo-section">
          <div className="section-shell">
            <div className="section-intro section-intro--on-dark section-intro--split">
              <div>
                <p className="section-label">Vos démonstrations détaillées</p>
                <h2>Deux emplacements pour raconter chaque côté du produit.</h2>
              </div>
              <p>Vous pourrez déposer vos montages sans reconstruire la page. Les cadres sont déjà responsives et prévus pour des sous-titres.</p>
            </div>
            <div className="video-duo">
              <VideoPlaceholder
                compact
                number="02"
                title="Le pipeline centre"
                description="Création d'un module, contrôles, audio et planification."
              />
              <VideoPlaceholder
                compact
                number="03"
                title="La classe apprenant"
                description="Connexion, attente, lecture synchronisée et Q&A."
              />
            </div>
          </div>
        </section>

        <section className="trace-section section-shell">
          <div className="trace-section__statement">
            <LockKeyhole size={34} />
            <h2>Le cadre pédagogique reste visible.</h2>
            <p>Chaque étape produit une trace exploitable par l'équipe centre, depuis la source jusqu'à la séance diffusée.</p>
          </div>
          <div className="trace-section__list">
            <div><FileCheck2 /><span><strong>Sources reliées</strong>Le contenu reste rattaché au référentiel de travail.</span></div>
            <div><Clock3 /><span><strong>Chronologie explicite</strong>Les séances et audios suivent un horaire défini.</span></div>
            <div><UsersRound /><span><strong>Espaces séparés</strong>Chaque promotion utilise ses propres accès et journaux.</span></div>
          </div>
        </section>

        <section className="faq-section section-shell">
          <div className="section-intro">
            <p className="section-label">Questions fréquentes</p>
            <h2>Ce que Cadrenza fait, et ce qu'il ne prétend pas faire.</h2>
          </div>
          <div className="faq-list">
            <details>
              <summary>Est-ce un catalogue de cours à la demande ?</summary>
              <p>Non. Cadrenza est conçu pour une classe planifiée, avec une heure de début, une playlist horodatée et un suivi par promotion.</p>
            </details>
            <details>
              <summary>Faut-il reconstruire le cours pour chaque promotion ?</summary>
              <p>Non. Le module est attaché au titre professionnel et peut être repris par plusieurs promotions avec des calendriers distincts.</p>
            </details>
            <details>
              <summary>Le centre garde-t-il la main sur la production ?</summary>
              <p>Oui. Les étapes, fichiers, horaires, états de verrouillage et journaux sont pilotés depuis l'espace centre.</p>
            </details>
            <details>
              <summary>Les apprenants parlent-ils à un avatar humain ?</summary>
              <p>Non. L'interface représente les fonctions IA comme des robots logiciels. L'expérience de cours reste centrée sur le contenu et la progression de la séance.</p>
            </details>
          </div>
        </section>

        <section className="final-cta">
          <div className="final-cta__grid" aria-hidden="true" />
          <div>
            <CadrenzaLogo compact />
            <p>Votre premier titre professionnel</p>
            <h2>Préparez le module. Cadencez les promotions.</h2>
          </div>
          <div className="final-cta__actions">
            <button className="button button--signal button--large" type="button" onClick={() => navigate('/connexion-centre?mode=signup')}>
              Créer un espace centre <ArrowRight size={18} />
            </button>
            <button className="button button--outline button--large" type="button" onClick={() => navigate('/connexion-centre')}>
              Se connecter
            </button>
          </div>
        </section>
      </main>

      <footer className="site-footer">
        <div className="site-footer__brand">
          <CadrenzaLogo />
          <p>Production et diffusion synchrone de parcours RNCP pour les centres de formation.</p>
        </div>
        <div className="site-footer__links">
          <div><strong>Découvrir</strong><a href="#methode">La méthode</a><a href="#agents">Les robots</a><a href="#experience">La classe</a></div>
          <div><strong>Accès</strong><a href="/connexion-centre">Espace centre</a><a href="/cours">Espace apprenant</a></div>
          <div><strong>Produit</strong><span>Modules RNCP</span><span>Classes synchrones</span><span>Pilotage multi-promotion</span></div>
        </div>
        <div className="site-footer__bottom">
          <span>© 2026 Cadrenza. Tous droits réservés.</span>
          <span>Conçu pour les parcours RNCP synchrones.</span>
        </div>
      </footer>
    </div>
  )
}
