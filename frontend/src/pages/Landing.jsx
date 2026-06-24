import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'

export default function Landing() {
  const navigate = useNavigate()
  const [navTheme, setNavTheme] = useState('transparent')

  useEffect(() => {
    const handleScroll = () => {
      const heroExitPoint = window.innerHeight - 80

      if (window.scrollY <= 16) {
        setNavTheme('transparent')
      } else if (window.scrollY < heroExitPoint) {
        setNavTheme('dark')
      } else {
        setNavTheme('light')
      }
    }

    handleScroll()
    window.addEventListener('scroll', handleScroll, { passive: true })

    return () => window.removeEventListener('scroll', handleScroll)
  }, [])

  const isLightNav = navTheme === 'light'
  const navBackgroundClass = {
    transparent: 'bg-transparent',
    dark: 'bg-[#03093d]/95 shadow-[0_1px_0_rgba(255,255,255,0.08)]',
    light: 'bg-white shadow-[0_1px_0_rgba(15,23,42,0.1)]',
  }[navTheme]
  const navLinkClass = isLightNav
    ? '!text-[#111111] hover:!text-[#111111]/70'
    : '!text-white hover:!text-white/70'
  const navButtonClass = isLightNav
    ? 'text-[#111111] hover:text-[#111111]/70'
    : 'text-white hover:text-white/70'
  const navTrialButtonClass = isLightNav
    ? 'text-[#111111] hover:text-[#111111]/70 text-sm font-bold transition'
    : 'bg-white text-[#5B5BFF] hover:bg-white/90 px-5 py-2.5 rounded-full text-sm font-bold shadow-lg transition transform hover:-translate-y-0.5'
  const navTextShadow = isLightNav ? 'none' : '0 1px 6px rgba(0,0,0,0.6)'

  return (
    <div className="bg-white text-[#1E293B] transition-colors duration-300" style={{ fontFamily: '"Plus Jakarta Sans", sans-serif' }}>

      {/* Navigation */}
      <nav
        className={`fixed w-full z-50 overflow-visible transition-colors duration-300 ${
          navBackgroundClass
        }`}
      >
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 overflow-visible">
          <div className="flex justify-between items-center h-20">
            <div className="flex items-center">
              <div className="hidden md:block">
                <div className="flex items-center space-x-8">
                  <a className={`${navLinkClass} px-3 py-2 rounded-md text-sm font-bold transition`} style={{ color: isLightNav ? '#111111' : '#fff', textShadow: navTextShadow }} href="#">Solutions</a>
                  <a className={`${navLinkClass} px-3 py-2 rounded-md text-sm font-bold transition`} style={{ color: isLightNav ? '#111111' : '#fff', textShadow: navTextShadow }} href="#">Tarifs</a>
                  <a className={`${navLinkClass} px-3 py-2 rounded-md text-sm font-bold transition`} style={{ color: isLightNav ? '#111111' : '#fff', textShadow: navTextShadow }} href="#">Ressources</a>
                  <button className={`${navButtonClass} text-sm font-bold transition`}>Connexion</button>
                  {!isLightNav && (
                    <button className={navTrialButtonClass}>
                      Essai gratuit
                    </button>
                  )}
                </div>
              </div>
            </div>
            <div />
          </div>
        </div>
      </nav>

      {/* Hero */}
      <section className="relative min-h-screen flex flex-col justify-center overflow-hidden" style={{ backgroundColor: '#03093d', backgroundImage: 'url(/fond-hero2.png)', backgroundSize: 'cover', backgroundPosition: 'center 15%' }}>
        <div className="absolute top-0 right-0 -mr-20 -mt-20 w-96 h-96 bg-[#5B5BFF]/10 rounded-full blur-3xl opacity-70"></div>
        <div className="absolute bottom-0 left-0 -ml-20 -mb-20 w-80 h-80 bg-[#FF6B8B]/10 rounded-full blur-3xl opacity-70"></div>
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 relative z-10 pt-24 pb-16">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-12 items-center">
            <div className="text-center lg:text-left">

              <h1 className="text-balance text-5xl lg:text-7xl font-display font-black leading-[1.12] tracking-[-0.03em] mb-8 text-white">
                Déployez une armée
                <br />
                de professeurs <span className="text-[#5B6DFF]">IA</span>
              </h1>
              <p className="text-lg text-white/80 mb-8 max-w-xl mx-auto lg:mx-0">
                Confiez-lui un titre professionnel, un rythme de cours et une durée. En quelques heures, il prépare l'année et dispense les sessions à vos élèves au jour prévu.
              </p>
              <div className="flex flex-col sm:flex-row items-center justify-center lg:justify-start gap-4">
                <button onClick={() => navigate('/hr-dashboard')} className="w-full sm:w-auto h-14 bg-[#3857FF] hover:bg-[#2946E8] text-white px-9 rounded-[10px] font-bold shadow-[0_14px_34px_rgba(56,87,255,0.35)] transition transform hover:-translate-y-1 inline-flex items-center justify-center gap-4 whitespace-nowrap">
                  Découvrir les professeurs IA
                  <span className="material-icons-round text-white text-2xl leading-none">arrow_forward</span>
                </button>
                <button className="w-full sm:w-auto h-14 bg-transparent border border-[#3857FF] text-white hover:bg-[#3857FF]/10 px-9 rounded-[10px] font-bold inline-flex items-center justify-center gap-3 transition whitespace-nowrap">
                  <span className="material-icons-round text-[#3857FF] text-2xl leading-none">play_circle</span>
                  Regarder une démo
                </button>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Trust */}
      <section className="py-12 bg-white">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <p className="text-center text-sm font-semibold text-gray-500 uppercase tracking-widest mb-8">Ils nous font confiance</p>
          <div className="flex flex-wrap justify-center items-center gap-12 opacity-60 grayscale hover:grayscale-0 transition-all duration-500">
            <div className="h-8 flex items-center justify-center font-display font-bold text-xl text-gray-800">
              <span className="material-icons-round mr-2">school</span> ACADEMY
            </div>
            <div className="h-8 flex items-center justify-center font-display font-bold text-xl text-gray-800">
              <span className="material-icons-round mr-2">business</span> CORP<span className="text-[#5B5BFF]">TECH</span>
            </div>
            <div className="h-8 flex items-center justify-center font-display font-bold text-xl text-gray-800">
              <span className="material-icons-round mr-2">architecture</span> FORM<span className="font-light">ASLEY</span>
            </div>
            <div className="h-8 flex items-center justify-center font-display font-bold text-xl text-gray-800">
              <span className="material-icons-round mr-2">all_inclusive</span> INFINITY
            </div>
            <div className="h-8 flex items-center justify-center font-display font-bold text-xl text-gray-800">
              <span className="material-icons-round mr-2">public</span> GLOBAL<span className="text-[#FF6B8B]">EDU</span>
            </div>
          </div>
          <div className="flex justify-center mt-10 gap-4">
            <button className="px-6 py-2 rounded-full border border-[#5B5BFF] text-[#5B5BFF] hover:bg-[#5B5BFF] hover:text-white transition text-sm font-medium">Nous contacter</button>
            <button className="px-6 py-2 rounded-full border border-gray-300 text-gray-600 hover:border-[#5B5BFF] hover:text-[#5B5BFF] transition text-sm font-medium">Voir les tarifs</button>
          </div>
        </div>
      </section>

      {/* Stats */}
      <section className="py-16 bg-[#5B5BFF] text-white relative overflow-hidden">
        <div className="absolute top-0 right-0 p-12 opacity-10">
          <span className="material-symbols-rounded text-9xl rotate-12">donut_large</span>
        </div>
        <div className="absolute bottom-0 left-0 p-8 opacity-10">
          <span className="material-symbols-rounded text-9xl -rotate-12">bar_chart</span>
        </div>
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 relative z-10">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-8 text-center divide-y md:divide-y-0 md:divide-x divide-white/20">
            <div className="p-4">
              <div className="flex justify-center mb-2">
                <span className="material-symbols-rounded text-4xl opacity-80">school</span>
              </div>
              <div className="text-5xl font-display font-bold mb-1">12</div>
              <div className="text-indigo-100 font-medium tracking-wide text-sm uppercase">Mois de cours préparés</div>
            </div>
            <div className="p-4">
              <div className="flex justify-center mb-2">
                <span className="material-symbols-rounded text-4xl opacity-80">apartment</span>
              </div>
              <div className="text-5xl font-display font-bold mb-1">1</div>
              <div className="text-indigo-100 font-medium tracking-wide text-sm uppercase">Professeur IA par formation</div>
            </div>
            <div className="p-4">
              <div className="flex justify-center mb-2">
                <span className="material-symbols-rounded text-4xl opacity-80">assignment_turned_in</span>
              </div>
              <div className="text-5xl font-display font-bold mb-1">0</div>
              <div className="text-indigo-100 font-medium tracking-wide text-sm uppercase">Formateur à mobiliser</div>
            </div>
          </div>
        </div>
      </section>

      {/* Features */}
      <section className="py-24 bg-white">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="text-center max-w-3xl mx-auto mb-20">
            <h2 className="text-3xl md:text-4xl font-display font-bold mb-6 text-[#1E293B]">
              Le professeur{' '}
              <span className="bg-indigo-100 text-[#5B5BFF] px-2 rounded transform -rotate-1 inline-block">IA</span>{' '}
              qui prépare et anime vos cours
            </h2>
            <p className="text-lg text-gray-600">
              Une solution SaaS pour créer une formation complète, planifier les sessions et délivrer les cours sans dépendre d'un formateur externe.
            </p>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-8">
            {[
              { icon: 'auto_awesome', color: 'text-[#5B5BFF]', title: 'Préparation annuelle', desc: 'Le professeur IA structure le parcours, les séances et les supports à partir du titre professionnel.' },
              { icon: 'description', color: 'text-[#FF6B8B]', title: 'Cours prêts à diffuser', desc: 'Chaque session est préparée avec son déroulé, son contenu pédagogique et ses ressources associées.' },
              { icon: 'hub', color: 'text-blue-400', title: 'Espace élèves dédié', desc: "Chaque formation dispose de son lien d'accès et de son environnement de cours sécurisé." },
              { icon: 'euro', color: 'text-green-500', title: 'Coûts maîtrisés', desc: "Réduisez la dépendance aux formateurs, aux plannings complexes et aux imprévus d'animation." },
            ].map(({ icon, color, title, desc }) => (
              <div key={title} className="bg-white p-8 rounded-2xl border border-transparent hover:border-[#5B5BFF]/20 transition-all duration-300 hover:shadow-xl group">
                <div className="w-14 h-14 bg-white rounded-xl shadow-sm flex items-center justify-center mb-6 group-hover:scale-110 transition-transform">
                  <span className={`material-symbols-rounded text-3xl ${color}`}>{icon}</span>
                </div>
                <h3 className="text-xl font-bold mb-3 text-[#1E293B]">{title}</h3>
                <p className="text-gray-600 text-sm leading-relaxed">{desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Integration */}
      <section className="py-20 bg-white overflow-hidden">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-16 items-center">
            <div>
              <h2 className="text-3xl font-display font-bold mb-6 text-[#1E293B]">
                Un professeur IA connecté à votre organisation
              </h2>
              <p className="text-gray-600 mb-6">
                Vous définissez le titre, le calendrier et la promo. La plateforme prépare le parcours, crée l'espace élève et garde les sessions prêtes pour toute l'année.
              </p>
              <ul className="space-y-4 mb-8">
                {['Création de formations par organisme', 'Liens élèves séparés par promo', 'Suivi sécurisé des accès et présences'].map((item) => (
                  <li key={item} className="flex items-center gap-3">
                    <span className="material-icons-round text-[#5B5BFF] bg-indigo-100 rounded-full p-1 text-sm">check</span>
                    <span className="text-gray-700 font-medium">{item}</span>
                  </li>
                ))}
              </ul>
            </div>
            <div className="relative flex items-center justify-center" style={{ height: '400px' }}>
              <div className="absolute w-[400px] h-[400px] border border-dashed border-[#5B5BFF]/30 rounded-full animate-spin" style={{ animationDuration: '60s' }}></div>
              <div className="absolute w-[280px] h-[280px] border border-gray-200 rounded-full"></div>
              <div className="relative z-10 w-24 h-24 bg-white rounded-full shadow-2xl flex items-center justify-center border-4 border-[#F8F7FF]">
                <div className="w-12 h-12 bg-[#5B5BFF] rounded-lg flex items-center justify-center text-white font-bold text-2xl">F</div>
              </div>
              <div className="absolute top-10 right-20 bg-white px-4 py-2 rounded-lg shadow-lg border border-gray-100 text-sm font-bold text-gray-700 animate-bounce" style={{ animationDelay: '0.5s' }}>RNCP</div>
              <div className="absolute bottom-10 left-20 bg-white px-4 py-2 rounded-lg shadow-lg border border-gray-100 text-sm font-bold text-gray-700 animate-bounce" style={{ animationDelay: '1s' }}>Promo</div>
              <div className="absolute bottom-20 right-10 bg-white px-4 py-2 rounded-lg shadow-lg border border-gray-100 text-sm font-bold text-gray-700 animate-bounce" style={{ animationDelay: '1.5s' }}>Élèves</div>
              <div className="absolute top-20 left-10 bg-white px-4 py-2 rounded-lg shadow-lg border border-gray-100 text-sm font-bold text-gray-700 animate-bounce" style={{ animationDelay: '2s' }}>Cours</div>
              <svg className="absolute inset-0 w-full h-full pointer-events-none" style={{ zIndex: 1 }}>
                <line stroke="#5B5BFF" strokeOpacity="0.2" strokeWidth="2" x1="50%" x2="70%" y1="50%" y2="20%"></line>
                <line stroke="#5B5BFF" strokeOpacity="0.2" strokeWidth="2" x1="50%" x2="30%" y1="50%" y2="80%"></line>
                <line stroke="#5B5BFF" strokeOpacity="0.2" strokeWidth="2" x1="50%" x2="80%" y1="50%" y2="70%"></line>
                <line stroke="#5B5BFF" strokeOpacity="0.2" strokeWidth="2" x1="50%" x2="20%" y1="50%" y2="30%"></line>
              </svg>
            </div>
          </div>
        </div>
      </section>

      {/* Audience */}
      <section className="py-24 bg-white">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="text-center mb-16">
            <h2 className="text-3xl md:text-4xl font-display font-bold text-[#1E293B]">
              FormIA à destination des centres de formation
            </h2>
            <div className="mt-4 flex justify-center">
              <svg fill="none" height="20" viewBox="0 0 100 20" width="100" xmlns="http://www.w3.org/2000/svg">
                <path d="M2 10C20 18 80 18 98 10" stroke="#FF6B8B" strokeLinecap="round" strokeWidth="3"></path>
              </svg>
            </div>
          </div>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
            <div className="bg-red-50/50 p-10 rounded-3xl border border-red-100 relative overflow-hidden group hover:shadow-lg transition-all">
              <div className="absolute top-0 right-0 w-32 h-32 bg-red-200/20 rounded-bl-full -mr-8 -mt-8 transition-transform group-hover:scale-110"></div>
              <h3 className="text-2xl font-bold text-[#FF6B8B] mb-2">Formation déléguée</h3>
              <p className="text-lg font-semibold text-gray-800 mb-6">À un professeur IA mandaté</p>
              <ul className="space-y-4 mb-8">
                {[
                  'Préparation complète du programme annuel',
                  'Cours dispensés au rythme choisi',
                  'Moins de contraintes de planning formateur',
                  'Tableau de bord par centre et par formation',
                ].map((point) => (
                  <li key={point} className="flex items-start gap-3">
                    <span className="material-icons-round text-[#FF6B8B] mt-1 text-sm">check_circle</span>
                    <span className="text-gray-600 text-sm">{point}</span>
                  </li>
                ))}
              </ul>
              <a className="inline-flex items-center text-[#FF6B8B] font-semibold hover:gap-2 transition-all" href="#">
                En savoir plus <span className="material-icons-round ml-1 text-sm">arrow_forward</span>
              </a>
            </div>
            <div className="bg-indigo-50/50 p-10 rounded-3xl border border-indigo-100 relative overflow-hidden group hover:shadow-lg transition-all">
              <div className="absolute top-0 right-0 w-32 h-32 bg-indigo-200/20 rounded-bl-full -mr-8 -mt-8 transition-transform group-hover:scale-110"></div>
              <h3 className="text-2xl font-bold text-[#5B5BFF] mb-2">Plateforme élève</h3>
              <p className="text-lg font-semibold text-gray-800 mb-6">Pour chaque formation créée</p>
              <ul className="space-y-4 mb-8">
                {[
                  'Lien de connexion dédié aux élèves',
                  "Comptes élèves rattachés à la bonne formation",
                  "Accès aux cours le jour prévu",
                  'Présence et progression visibles par le centre',
                ].map((point) => (
                  <li key={point} className="flex items-start gap-3">
                    <span className="material-icons-round text-[#5B5BFF] mt-1 text-sm">check_circle</span>
                    <span className="text-gray-600 text-sm">{point}</span>
                  </li>
                ))}
              </ul>
              <a className="inline-flex items-center text-[#5B5BFF] font-semibold hover:gap-2 transition-all" href="#">
                En savoir plus <span className="material-icons-round ml-1 text-sm">arrow_forward</span>
              </a>
            </div>
          </div>
        </div>
      </section>

      {/* Differentiators */}
      <section className="py-20 bg-white">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="text-center mb-16">
            <h2 className="text-3xl font-display font-bold text-[#1E293B]">
              Ce qui fait toute{' '}
              <span className="relative z-10">
                notre différence
                <span className="absolute bottom-1 left-0 w-full h-3 bg-[#FF6B8B]/30 -z-10 rounded-sm"></span>
              </span>
            </h2>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
            {[
              {
                icon: 'extension', color: 'text-[#FF6B8B]', bg: 'bg-pink-100',
                title: 'Économie',
                desc: "Réduisez le coût et l'incertitude liés au recrutement, au planning et à la disponibilité des formateurs.",
                extra: null,
              },
              {
                icon: 'support_agent', color: 'text-[#5B5BFF]', bg: 'bg-indigo-100',
                title: 'Disponibilité',
                desc: "Le professeur IA prépare l'année en amont et reste prêt à dispenser les cours aux créneaux mandatés.",
                extra: null,
              },
              {
                icon: 'lock_person', color: 'text-green-500', bg: 'bg-green-100',
                title: 'Séparation',
                desc: 'Vos centres, formations, administrateurs et élèves restent clairement isolés dans leur espace.',
                extra: <div className="mt-4 flex justify-center"><span className="material-icons-round text-gray-400 text-3xl">verified_user</span></div>,
              },
            ].map(({ icon, color, bg, title, desc, extra }) => (
              <div key={title} className="bg-white p-8 rounded-2xl shadow-sm text-center border border-gray-100">
                <div className={`w-20 h-20 mx-auto ${bg} rounded-full flex items-center justify-center mb-6`}>
                  <span className={`material-symbols-rounded text-4xl ${color}`}>{icon}</span>
                </div>
                <h3 className="text-xl font-bold mb-3">{title}</h3>
                <p className="text-sm text-gray-600">{desc}</p>
                {extra}
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Testimonials */}
      <section className="py-24 bg-white relative overflow-hidden">
        <div className="absolute top-0 left-0 w-64 h-64 bg-[#FF6B8B]/5 rounded-full blur-3xl -ml-20 -mt-20"></div>
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="text-center mb-12">
            <h2 className="text-3xl font-display font-bold text-[#1E293B] flex items-center justify-center gap-2">
              Nos clients{' '}
              <span className="bg-[#5B5BFF] text-white px-2 py-0.5 rounded transform -rotate-2 text-2xl">parlent</span>{' '}
              de FormIA !
              <span className="material-icons-round text-gray-400">chat_bubble_outline</span>
            </h2>
            <p className="text-gray-500 mt-4 text-sm">Découvrez comment les organismes imaginent leur professeur IA.</p>
          </div>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-12 items-center">
            <div className="relative bg-white p-10 rounded-3xl border-2 border-[#FF6B8B]/20 shadow-xl">
              <div className="absolute -top-5 left-10 bg-white px-2">
                <span className="material-icons-round text-[#FF6B8B] text-5xl">format_quote</span>
              </div>
              <h3 className="text-xl font-bold mb-4 mt-2">Moins de dépendance - Plus de régularité</h3>
              <p className="text-gray-600 italic mb-6 leading-relaxed">
                "Nous voulions ouvrir plus de sessions sans multiplier les formateurs ni subir les contraintes de planning. Le professeur IA nous donne une base régulière, prête à dispenser les cours chaque semaine."
              </p>
              <p className="text-sm text-gray-500 font-medium">
                Le centre garde le contrôle, les élèves gardent un cadre, et l'organisation respire.
              </p>
              <div className="absolute bottom-6 right-6">
                <svg fill="none" height="40" viewBox="0 0 40 40" width="40" xmlns="http://www.w3.org/2000/svg">
                  <path d="M5 35C15 35 15 25 25 25C35 25 35 15 35 5" stroke="#FF6B8B" strokeLinecap="round" strokeWidth="2"></path>
                </svg>
              </div>
            </div>
            <div className="space-y-6">
              {[
                { initials: 'CF', bg: 'bg-blue-100', color: 'text-blue-600', name: 'Centre de formation pilote', role: 'Direction pédagogique' },
                { initials: 'RN', bg: 'bg-purple-100', color: 'text-purple-600', name: 'Organisme RNCP', role: 'Responsable formation' },
                { initials: 'CA', bg: 'bg-green-100', color: 'text-green-600', name: 'Campus alternance', role: 'Coordination pédagogique' },
              ].map(({ initials, bg, color, name, role }) => (
                <div key={name} className="bg-white p-4 rounded-2xl flex items-center gap-4 hover:shadow-md transition cursor-pointer border border-transparent hover:border-[#5B5BFF]/30">
                  <div className={`w-12 h-12 ${bg} rounded-full flex items-center justify-center ${color} font-bold`}>{initials}</div>
                  <div>
                    <h4 className="font-bold text-[#1E293B]">{name}</h4>
                    <p className="text-xs text-gray-500">{role}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* Contact */}
      <section className="py-24 bg-white">
        <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="text-center mb-12">
            <h2 className="text-3xl font-display font-bold mb-4 text-[#1E293B]">Contactez notre équipe</h2>
            <p className="text-gray-600 max-w-2xl mx-auto">
              Vous voulez voir comment un professeur IA peut préparer et assurer une formation sur un an ? Prenez rendez-vous et montrez-nous votre contexte.
            </p>
          </div>
          <div className="bg-white rounded-3xl shadow-2xl overflow-hidden border border-gray-100 flex flex-col md:flex-row" style={{ minHeight: '400px' }}>
            <div className="p-8 w-full md:w-1/3 border-b border-gray-100 md:border-b-0 md:border-r">
              <div className="flex items-center gap-3 mb-6">
                <div className="w-10 h-10 rounded-full bg-gray-200 flex items-center justify-center">
                  <span className="material-icons-round text-gray-500">person</span>
                </div>
                <div>
                  <p className="text-xs text-gray-500 font-medium">Nicolas Ansellem</p>
                  <h4 className="font-bold text-sm">Découvrez FormIA - Démo live</h4>
                </div>
              </div>
              <div className="space-y-4 text-sm text-gray-600">
                <div className="flex items-center gap-2">
                  <span className="material-icons-round text-gray-400 text-lg">schedule</span>
                  <span>30 min</span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="material-icons-round text-gray-400 text-lg">videocam</span>
                  <span>Google Meet</span>
                </div>
                <p className="text-xs mt-4 leading-relaxed">
                  Participez à un échange pour voir comment mandater un professeur IA sur une formation, une promo et un calendrier précis.
                </p>
              </div>
            </div>
            <div className="p-8 w-full md:w-2/3 bg-white">
              <h3 className="font-bold text-lg mb-6">Sélectionnez une date et une heure</h3>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
                <div>
                  <div className="flex justify-between items-center mb-4">
                    <span className="font-bold text-sm">Février 2024</span>
                    <div className="flex gap-2">
                      <span className="material-icons-round text-gray-400 text-sm cursor-pointer">chevron_left</span>
                      <span className="material-icons-round text-gray-800 text-sm cursor-pointer">chevron_right</span>
                    </div>
                  </div>
                  <div className="grid grid-cols-7 gap-1 text-center text-xs mb-2 text-gray-400">
                    {['SUN', 'MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT'].map((d) => <div key={d}>{d}</div>)}
                  </div>
                  <div className="grid grid-cols-7 gap-1 text-center text-sm">
                    <div className="p-2 text-gray-300">28</div>
                    <div className="p-2 text-gray-300">29</div>
                    {[1, 2, 3, 4, 5, 6, 7].map((n) => (
                      <div key={n} className="p-2 hover:bg-white rounded-full cursor-pointer">{n}</div>
                    ))}
                    <div className="p-2 bg-[#5B5BFF] text-white rounded-full cursor-pointer">8</div>
                    <div className="p-2 hover:bg-white rounded-full cursor-pointer">9</div>
                  </div>
                </div>
                <div className="space-y-2 max-h-64 overflow-y-auto pr-2">
                  <div className="text-sm font-medium mb-2">Mercredi 8</div>
                  <button className="w-full py-2 border border-[#5B5BFF] text-[#5B5BFF] rounded hover:bg-[#5B5BFF] hover:text-white transition text-sm font-medium">09:00</button>
                  {['09:30', '10:00', '10:30', '11:00'].map((time) => (
                    <button key={time} className="w-full py-2 border border-gray-200 text-[#5B5BFF] rounded hover:border-[#5B5BFF] hover:bg-[#5B5BFF] hover:text-white transition text-sm font-medium">{time}</button>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="bg-gray-900 text-gray-300 py-16">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="grid grid-cols-1 md:grid-cols-4 gap-12 mb-12">
            <div>
              <p className="text-sm text-gray-400 mb-6">
                Professeur IA pour centres de formation qui veulent créer, planifier et délivrer leurs cours avec moins de contraintes opérationnelles.
              </p>
              <div className="flex gap-4">
                <a className="text-gray-400 hover:text-white transition" href="#"><span className="material-icons-round">facebook</span></a>
                <a className="text-gray-400 hover:text-white transition" href="#"><span className="material-icons-round">smart_display</span></a>
                <a className="text-gray-400 hover:text-white transition" href="#"><span className="material-icons-round">alternate_email</span></a>
              </div>
            </div>
            <div>
              <h4 className="text-white font-bold mb-4">Produit</h4>
              <ul className="space-y-2 text-sm">
                {['Professeur IA', 'Tarifs', 'Formations', 'Mises à jour'].map((item) => (
                  <li key={item}><a className="hover:text-[#5B5BFF] transition" href="#">{item}</a></li>
                ))}
              </ul>
            </div>
            <div>
              <h4 className="text-white font-bold mb-4">Ressources</h4>
              <ul className="space-y-2 text-sm">
                {['Blog', "Centre d'aide", 'Démo', 'Guides'].map((item) => (
                  <li key={item}><a className="hover:text-[#5B5BFF] transition" href="#">{item}</a></li>
                ))}
              </ul>
            </div>
            <div>
              <h4 className="text-white font-bold mb-4">Newsletter</h4>
              <p className="text-sm text-gray-400 mb-4">Inscrivez-vous pour recevoir nos actualités.</p>
              <form className="flex flex-col gap-2" onSubmit={(e) => e.preventDefault()}>
                <input
                  className="bg-gray-800 border-none rounded-lg px-4 py-2 text-sm text-white outline-none focus:ring-2 focus:ring-[#5B5BFF]"
                  placeholder="Votre email"
                  type="email"
                />
                <button className="bg-[#5B5BFF] hover:bg-[#4040CC] text-white px-4 py-2 rounded-lg text-sm font-semibold transition" type="submit">S'inscrire</button>
              </form>
            </div>
          </div>
          <div className="border-t border-gray-800 pt-8 flex flex-col md:flex-row justify-between items-center text-xs text-gray-500">
            <p>© 2026 FormIA. Tous droits réservés.</p>
            <div className="flex gap-6 mt-4 md:mt-0">
              {['CGU centres', 'CGU élèves', 'Mentions légales', 'Gestion des cookies'].map((item) => (
                <a key={item} className="hover:text-white transition" href="#">{item}</a>
              ))}
            </div>
          </div>
        </div>
      </footer>

    </div>
  )
}
