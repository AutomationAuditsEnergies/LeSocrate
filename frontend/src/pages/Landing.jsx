import { useEffect, useState } from 'react'
import { WhatsAppDemo } from '@/sections/CharlySection/components/WhatsAppDemo'
import './Landing.css'

const featureRows = [
  {
    icon: '/uifry/star-05.svg',
    title: 'Planifiez chaque promotion',
    copy: 'Choisissez les jours de formation et la durée du parcours avant le démarrage.',
  },
  {
    icon: '/uifry/cube-04.svg',
    title: 'Un module, toutes vos promotions',
    copy: 'Produisez une fois le module associé à un titre RNCP, puis réutilisez-le à chaque nouvelle promotion.',
  },
  {
    icon: '/uifry/cube-02.svg',
    title: 'Gardez la main sur vos cours',
    copy: 'Ajustez le planning et suivez la préparation des contenus depuis un seul espace.',
  },
]

const teacherAdvantages = [
  { icon: '/uifry/bell.svg', title: 'Ils animent les journées de formation' },
  { icon: '/uifry/star-05.svg', title: 'Ils préparent des supports visuels' },
  { icon: '/uifry/cube-02.svg', title: 'Ils interagissent avec les élèves' },
]

const faqItems = [
  {
    question: 'Cadrenza, c’est quoi ?',
    answer: 'Cadrenza est une plateforme de formation qui vous aide à préparer, planifier et animer des parcours certifiants avec des professeurs IA.',
  },
  {
    question: 'Comment fonctionnent les professeurs IA ?',
    answer: 'Ils préparent les supports visuels, suivent le planning de la promotion, animent les journées de formation et répondent aux élèves à partir du contenu du cours.',
  },
  {
    question: 'Faut-il des compétences techniques pour utiliser Cadrenza ?',
    answer: 'Non. Vous définissez le titre préparé, les jours de formation et la durée du parcours. Cadrenza organise ensuite les contenus et les sessions depuis votre espace.',
  },
  {
    question: 'Cadrenza convient-il à mon activité ?',
    answer: 'Cadrenza s’adresse aux organismes et centres de formation qui proposent des parcours certifiants et souhaitent réutiliser un même module pour plusieurs promotions.',
  },
  {
    question: 'Cadrenza et ChatGPT, quelle différence ?',
    answer: 'ChatGPT est un assistant généraliste. Cadrenza organise un parcours complet : supports, planning, animation en direct et interactions pédagogiques dans le cadre défini par votre centre.',
  },
  {
    question: 'Combien coûte Cadrenza ?',
    answer: 'Le tarif dépend du nombre de formations, de promotions et de professeurs IA utilisés. Nous vous proposons une estimation adaptée à votre organisation.',
  },
]

function Spark({ className = '' }) {
  return <img aria-hidden="true" className={`uifry-spark ${className}`} src="/uifry/spark.svg" />
}

function CadrenzaBrand({ footer = false }) {
  return (
    <span className={`uifry-brand${footer ? ' uifry-footer-logo' : ''}`}>
      <span className="uifry-brand-mark" aria-hidden="true" />
      <span className="uifry-brand-name">Cadrenza</span>
    </span>
  )
}

function PrimaryCta({ compact = false }) {
  return (
    <a className={`cadrenza-cta cadrenza-cta-primary${compact ? ' is-compact' : ''}`} href="/connexion-centre?mode=signup">
      Créer un espace <span aria-hidden="true">›</span>
    </a>
  )
}

function LoginCta({ compact = false }) {
  return (
    <a className={`cadrenza-cta cadrenza-cta-secondary${compact ? ' is-compact' : ''}`} href="/connexion-centre">
      Se connecter
    </a>
  )
}

function HeroPromptCard() {
  return (
    <div className="uifry-prompt-card">
      <div className="uifry-prompt-copy">
        <svg aria-hidden="true" viewBox="0 0 24 24">
          <path d="m14.5 5.5 4 4M4 20l3.5-1 10-10a2.8 2.8 0 0 0-4-4l-10 10L4 20Zm12-3.5v5m-2.5-2.5h5" />
        </svg>
        <p>
          J’ai besoin que tu animes une journée de formation de 8h à 17h lundi prochain.<br />
          Tu prépareras des diapositives et tu intéragiras avec les élèves.
        </p>
      </div>

      <div className="uifry-prompt-footer">
        <div className="uifry-agent-pill" aria-label="Professeur sélectionné : Pierre">
          <span className="uifry-agent-avatar"><img src="/robot-blue.png" alt="" /></span>
          <span>Pierre</span>
          <span className="uifry-agent-chevron" aria-hidden="true">⌄</span>
        </div>
        <div className="uifry-prompt-actions">
          <PrimaryCta compact />
          <LoginCta compact />
        </div>
      </div>
    </div>
  )
}

function LandingHeader() {
  const [scrolled, setScrolled] = useState(false)

  useEffect(() => {
    const updateHeader = () => setScrolled(window.scrollY > 12)
    updateHeader()
    window.addEventListener('scroll', updateHeader, { passive: true })
    return () => window.removeEventListener('scroll', updateHeader)
  }, [])

  return (
    <header className={`uifry-header${scrolled ? ' is-scrolled' : ''}`}>
      <nav className="uifry-nav" aria-label="Navigation principale">
        <a href="#home">Accueil</a>
        <a href="#advantages">Professeurs IA</a>
        <a href="#features">Planification</a>
        <a href="#classe">Économies</a>
        <a href="#pilotage">Témoignages</a>
        <a href="#faq">FAQ</a>
      </nav>

      <div className="uifry-header-actions">
        <LoginCta compact />
        <a className="uifry-phone-cta" href="tel:+33768533382" aria-label="Appeler le +33 7 68 53 33 82">
          <img src="/uifry/phone.svg" alt="" />
          +33 7 68 53 33 82
        </a>
      </div>

      <details className="uifry-mobile-nav">
        <summary aria-label="Ouvrir le menu"><span /><span /><span /></summary>
        <nav aria-label="Navigation mobile">
          <a href="#home">Accueil</a>
          <a href="#advantages">Professeurs IA</a>
          <a href="#features">Planification</a>
          <a href="#classe">Économies</a>
          <a href="#pilotage">Témoignages</a>
          <a href="#faq">FAQ</a>
          <a href="/connexion-centre">Se connecter</a>
          <a href="/connexion-centre?mode=signup">Créer un espace</a>
        </nav>
      </details>
    </header>
  )
}

function Hero() {
  return (
    <section className="uifry-hero" id="home">
      <Spark className="uifry-hero-spark-left" />
      <Spark className="uifry-hero-spark-right" />

      <div className="uifry-hero-copy">
        <h1>
          <span className="uifry-title-line">
            Des <span className="uifry-title-accent">professeurs IA</span>
            <span className="uifry-title-robot" aria-hidden="true"><img src="/robot-blue.png" alt="" /></span>
            pour
          </span>
          <br />délivrer vos formations.
        </h1>
      </div>

      <HeroPromptCard />
      <a className="uifry-scroll-cue" href="#features" aria-label="Découvrir la suite de la page">
        <span>Découvrir la suite</span>
        <svg aria-hidden="true" viewBox="0 0 24 24">
          <path d="m7 10 5 5 5-5" />
        </svg>
      </a>
    </section>
  )
}

function PremiumSection() {
  return (
    <section className="uifry-feature uifry-feature-premium" id="features">
      <Spark className="uifry-section-spark" />
      <div className="uifry-visual-shell uifry-planner-phone-shell">
        <img className="uifry-planner-reference-orbits" src="/uifry/notification-visual.png" alt="" aria-hidden="true" />
        <WhatsAppDemo />
      </div>

      <div className="uifry-feature-copy">
        <p className="uifry-kicker">Fini le stress opérationnel</p>
        <h2>Programmez vos cours à l’avance</h2>
        <div className="uifry-feature-list">
          {featureRows.map((item) => (
            <article className="uifry-feature-row" key={item.icon}>
              <h3><img src={item.icon} alt="" />{item.title}</h3>
              <p>{item.copy}</p>
            </article>
          ))}
        </div>
      </div>
    </section>
  )
}

function AdvantagesSection() {
  return (
    <section className="uifry-feature uifry-feature-advantages" id="advantages">
      <div className="uifry-feature-copy">
        <h2>Ce que nos professeurs IA apportent</h2>
        <div className="uifry-advantage-list">
          {teacherAdvantages.map((advantage) => (
            <article className="uifry-advantage-copy" key={advantage.title}>
              <h3>
                <span><img src={advantage.icon} alt="" /></span>
                {advantage.title}
              </h3>
            </article>
          ))}
        </div>
      </div>

      <div className="uifry-visual-shell uifry-notification-shell">
        <div className="uifry-taped-frame">
          <img
            className="uifry-classroom-visual"
            src="/uifry/classroom-training.png"
            alt="Un professeur robot présente une diapositive devant trois postes de formation"
          />
        </div>
      </div>
      <Spark className="uifry-advantages-spark" />
    </section>
  )
}

function CustomizableSection() {
  const [daysPerWeek, setDaysPerWeek] = useState(2)
  const [weeks, setWeeks] = useState(8)
  const trainingDays = daysPerWeek * weeks
  const freelanceCost = trainingDays * 650
  const cadrenzaCost = trainingDays * 30
  const savings = freelanceCost - cadrenzaCost
  const savingsPercent = Math.round((savings / freelanceCost) * 100)
  const formatEuros = (amount) => new Intl.NumberFormat('fr-FR').format(amount) + ' €'

  return (
    <section className="uifry-feature uifry-feature-customizable" id="classe">
      <article className="uifry-customizable-copy">
        <div className="uifry-saving-benefit">
          <span><img src="/uifry/hourglass.png" alt="" /></span>
          <div>
            <h2>Économisez du temps</h2>
            <p>Cadrenza prépare les supports, organise le parcours et anime les journées de formation.</p>
          </div>
        </div>
        <div className="uifry-saving-benefit">
          <span><img src="/uifry/savings.png" alt="" /></span>
          <div>
            <h2>Économisez de l’argent</h2>
            <p>Comparez le coût d’un professeur IA avec celui d’un formateur freelance.</p>
          </div>
        </div>
      </article>

      <div className="uifry-savings-calculator" aria-label="Calculateur d’économies">
        <div className="uifry-calculator-control">
          <label htmlFor="training-days">Journées de formation <strong>{daysPerWeek} j / semaine</strong></label>
          <input id="training-days" min="1" max="5" type="range" value={daysPerWeek} onChange={(event) => setDaysPerWeek(Number(event.target.value))} />
        </div>

        <div className="uifry-calculator-control">
          <label htmlFor="training-weeks">Durée du parcours <strong>{weeks} semaines</strong></label>
          <input id="training-weeks" min="1" max="52" type="range" value={weeks} onChange={(event) => setWeeks(Number(event.target.value))} />
        </div>

        <div className="uifry-calculator-comparison">
          <p><span>Formateur freelance</span><strong>{formatEuros(freelanceCost)}</strong></p>
          <p className="is-cadrenza"><span>Professeur IA Cadrenza</span><strong>{formatEuros(cadrenzaCost)}</strong></p>
        </div>

        <div className="uifry-calculator-result">
          <div><span>Budget économisé</span><strong>{formatEuros(savings)}</strong></div>
          <p>Soit <strong>{savingsPercent}%</strong> d’économie par rapport au budget freelance.</p>
        </div>
      </div>
    </section>
  )
}

function TestimonialSection() {
  const avatars = ['/uifry/avatar-1.svg', '/uifry/avatar-2.svg', '/uifry/avatar-3.svg', '/uifry/avatar-4.svg', '/uifry/avatar-5.svg']

  return (
    <section className="uifry-testimonial" id="pilotage" aria-labelledby="testimonial-heading">
      <header>
        <p>Testimonial</p>
        <h2 id="testimonial-heading">What Our Users<br />Say About Us?</h2>
      </header>

      <div className="uifry-testimonial-grid">
        <div className="uifry-testimonial-visual">
          <img src="/uifry/testimonial-visual.png" alt="Portraits de cinq utilisateurs de Uifry" />
        </div>
        <blockquote>
          <h3>The Best Financial Accounting App Ever!</h3>
          <p>
            “Arcu at dictum sapien, mollis. Vulputate sit id accumsan,
            ultricies. In ultrices malesuada elit mauris etiam odio. Duis
            tristique lacus, et blandit viverra nisl velit. Sed mattis
            rhoncus, diam suspendisse sit nunc, gravida eu. Lectus eget eget
            ac dolor neque lorem sapien, suspendisse aliquam.”
          </p>
          <div className="uifry-avatar-row" aria-label="Autres témoignages">
            {avatars.map((avatar, index) => (
              <img className={index === 0 ? 'is-current' : ''} src={avatar} alt="" key={avatar} />
            ))}
          </div>
          <cite>Nick Jonas</cite>
        </blockquote>
      </div>
      <Spark className="uifry-testimonial-spark" />
    </section>
  )
}

function FaqSection() {
  const [openItem, setOpenItem] = useState(null)

  return (
    <section className="uifry-faq" id="faq" aria-labelledby="faq-heading">
      <header>
        <p className="uifry-kicker">FAQ</p>
        <h2 id="faq-heading">Questions fréquentes</h2>
      </header>
      <div className="uifry-faq-list">
        {faqItems.map((item, index) => (
          <div className={`uifry-faq-item${openItem === index ? ' is-open' : ''}`} key={item.question}>
            <h3>
              <button
                aria-controls={`faq-answer-${index}`}
                aria-expanded={openItem === index}
                id={`faq-question-${index}`}
                onClick={() => setOpenItem(openItem === index ? null : index)}
                type="button"
              >
                {item.question}
              </button>
            </h3>
            <div
              aria-labelledby={`faq-question-${index}`}
              className="uifry-faq-answer"
              id={`faq-answer-${index}`}
              role="region"
            >
              <div><p>{item.answer}</p></div>
            </div>
          </div>
        ))}
      </div>
    </section>
  )
}

function DownloadSection() {
  const requestOnboarding = (event) => {
    event.preventDefault()
    const email = new FormData(event.currentTarget).get('email')
    const subject = encodeURIComponent('Demande d’accompagnement Cadrenza')
    const body = encodeURIComponent(`Bonjour,\n\nJe souhaite être accompagné(e) par un conseiller Cadrenza.\nVous pouvez me recontacter à cette adresse : ${email}`)
    window.location.href = `mailto:secretariat@saleshacking.fr?subject=${subject}&body=${body}`
  }

  return (
    <section className="uifry-download-section" id="download">
      <div className="uifry-glow uifry-glow-download" aria-hidden="true" />
      <Spark className="uifry-download-spark-left" />
      <Spark className="uifry-download-spark-right" />
      <div className="uifry-download-left-column">
        <article className="uifry-onboarding-card">
          <h3>Besoin d’être accompagné&nbsp;?</h3>
          <p>Appelez-nous, écrivez-nous ou laissez votre e-mail pour être recontacté.</p>

          <div className="uifry-onboarding-contacts">
            <a href="tel:+33768533382">
              <span className="uifry-onboarding-icon is-phone" aria-hidden="true" />
              +33 7 68 53 33 82
            </a>
            <a href="mailto:secretariat@saleshacking.fr">
              <span className="uifry-onboarding-icon is-mail" aria-hidden="true" />
              secretariat@saleshacking.fr
            </a>
          </div>

          <form className="uifry-onboarding-form" onSubmit={requestOnboarding}>
            <label htmlFor="onboarding-email">Votre adresse e-mail</label>
            <div>
              <input id="onboarding-email" name="email" type="email" autoComplete="email" placeholder="vous@entreprise.fr" required />
              <button
                className="cadrenza-cta cadrenza-cta-primary uifry-onboarding-submit"
                type="submit"
                aria-label="Envoyer mon adresse e-mail"
                title="Être recontacté"
              >
                <span aria-hidden="true">→</span>
              </button>
            </div>
          </form>
        </article>
      </div>
      <div className="uifry-download-visual">
        <span className="uifry-download-ring uifry-download-ring-one" aria-hidden="true" />
        <span className="uifry-download-ring uifry-download-ring-two" aria-hidden="true" />
      </div>
    </section>
  )
}

function LandingFooter() {
  return (
    <footer className="uifry-footer">
      <div className="uifry-footer-grid">
        <div className="uifry-footer-contact">
          <CadrenzaBrand footer />
          <div className="uifry-footer-details">
            <a href="mailto:secretariat@saleshacking.fr"><span className="uifry-footer-icon is-mail" aria-hidden="true" />secretariat@saleshacking.fr</a>
            <a href="tel:+33768533382"><span className="uifry-footer-icon is-phone" aria-hidden="true" />+33 7 68 53 33 82</a>
          </div>
        </div>
      </div>
      <p className="uifry-copyright">Copyright © 2026 Cadrenza. Tous droits réservés.</p>
    </footer>
  )
}

export default function Landing() {
  useEffect(() => {
    const previousTitle = document.title
    document.documentElement.classList.add('uifry-landing-active')
    document.body.classList.add('uifry-landing-active')
    document.title = 'Cadrenza'

    return () => {
      document.documentElement.classList.remove('uifry-landing-active')
      document.body.classList.remove('uifry-landing-active')
      document.title = previousTitle
    }
  }, [])

  return (
    <div className="uifry-landing">
      <div className="uifry-page">
        <LandingHeader />
        <main>
          <Hero />
          <PremiumSection />
          <AdvantagesSection />
          <CustomizableSection />
          <TestimonialSection />
          <FaqSection />
          <DownloadSection />
        </main>
        <LandingFooter />
      </div>
    </div>
  )
}
