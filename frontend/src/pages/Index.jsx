import { useNavigate } from 'react-router-dom'
import { useState } from 'react'
import Spline from '@splinetool/react-spline'

export default function Index() {
  const navigate = useNavigate()
  const [splineLoaded, setSplineLoaded] = useState(false)

  const handleFormSubmit = async (event) => {
    event.preventDefault()

    const formData = new FormData(event.target)
    const nom = formData.get('nom')
    const prenom = formData.get('prenom')

    try {
      const response = await fetch('/api/auth/login', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ nom, prenom }),
      })

      const data = await response.json()

      if (data.success) {
        // Connexion réussie, rediriger vers la page vidéo
        navigate('/video')
      } else {
        alert(data.error || 'Erreur lors de la connexion')
      }
    } catch (error) {
      console.error('Erreur connexion:', error)
      alert('Impossible de se connecter au serveur')
    }
  }


  return (
    <div
      className="min-h-screen px-4 lg:px-8 relative flex flex-col overflow-hidden"
      style={{
        backgroundImage: 'url("/static/images/rocket.jpg")',
        backgroundSize: 'cover',
        backgroundPosition: 'center',
        fontFamily: 'Poppins, sans-serif',
      }}
    >
      <header className="fixed top-0 left-0 w-full h-16 bg-gradient-to-b from-black/20 to-transparent z-50" />

      <main className="relative isolate flex-1 flex items-center justify-end pr-6 md:pr-12 lg:pr-20">
        {/* Calque Spline en arrière-plan, n'affecte pas le layout */}
        <div className="absolute inset-0 pointer-events-none" style={{ zIndex: 0 }}>
          <div
            style={{
              position: 'absolute',
              top: '10%',
              left: '5%',
              width: '50%',
              height: '80%',
              opacity: splineLoaded ? 0.8 : 0,
              transform: splineLoaded ? 'scale(1)' : 'scale(0.95)',
              transition: 'opacity 1.5s ease-out, transform 1.5s ease-out',
              willChange: 'opacity, transform'
            }}
          >
            <Spline
              scene="https://prod.spline.design/Td1yXokrn9dRpNzQ/scene.splinecode"
              style={{ width: '100%', height: '100%' }}
              onLoad={() => setTimeout(() => setSplineLoaded(true), 100)}
            />
          </div>
        </div>

        <div className="relative z-10 bg-white/95 backdrop-blur-md rounded-3xl shadow-2xl p-10 w-full max-w-md text-left ring-1 ring-white/30">
          <div className="absolute -top-10 left-1/2 -translate-x-1/2 bg-pink-500 rounded-full w-20 h-20 flex items-center justify-center shadow-md">
            <svg className="w-8 h-8 text-white" fill="currentColor" viewBox="0 0 24 24">
              <circle cx="12" cy="8" r="4" />
              <path d="M4 20c0-4 4-6 8-6s8 2 8 6v1H4z" />
            </svg>
          </div>
          <h2 className="text-2xl mt-12 font-bold text-pink-600 mb-6">Démarrez votre ascension</h2>
          <form className="space-y-5 text-left" onSubmit={handleFormSubmit}>
            <div>
              <label className="block text-gray-700 font-semibold mb-1" htmlFor="nom">
                Nom :
              </label>
              <input
                id="nom"
                name="nom"
                type="text"
                required
                className="w-full px-4 py-2 bg-gray-100 border border-gray-300 rounded-full focus:outline-none focus:ring-2 focus:ring-pink-400"
              />
            </div>
            <div>
              <label className="block text-gray-700 font-semibold mb-1" htmlFor="prenom">
                Prénom :
              </label>
              <input
                id="prenom"
                name="prenom"
                type="text"
                required
                className="w-full px-4 py-2 bg-gray-100 border border-gray-300 rounded-full focus:outline-none focus:ring-2 focus:ring-pink-400"
              />
            </div>
            <button
              type="submit"
              className="w-full bg-gradient-to-r from-pink-500 to-fuchsia-600 text-white font-semibold py-2 rounded-full hover:opacity-90 transition duration-200"
            >
              Entrer au cours
            </button>
          </form>
          <p className="mt-6 text-center text-sm text-gray-500">
            Bon apprentissage et bonne participation !
          </p>
        </div>
      </main>

      <footer className="w-full text-center text-white py-4 mt-10 border-t border-white/20">
        <p className="text-sm">&copy; 2025 Sales Hacking. Tous droits réservés.</p>
      </footer>
    </div>
  )
}
