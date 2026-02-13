export default function Intro() {
  return (
    <div className="bg-gray-900 text-white min-h-screen flex items-center justify-center">
      <div className="text-center">
        <h1 className="text-4xl font-bold mb-6">🎓 Formation terminée !</h1>
        <p className="text-xl mb-8">Bienvenue Prénom Nom</p>
        <p className="text-lg mb-8">Découvrez maintenant les fonctionnalités de notre plateforme</p>

        <div className="space-x-4">
          <button
            onClick={() => (window.location.href = '/video')}
            className="bg-blue-600 hover:bg-blue-700 px-6 py-3 rounded-lg font-medium transition"
          >
            Retour au cours
          </button>
          <button
            onClick={() => (window.location.href = '/logout')}
            className="bg-gray-600 hover:bg-gray-700 px-6 py-3 rounded-lg font-medium transition"
          >
            Se déconnecter
          </button>
        </div>
      </div>
    </div>
  )
}
