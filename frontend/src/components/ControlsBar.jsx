export default function ControlsBar({
  participantsCount = 0,
  onToggleChat,
  onToggleParticipants,
  onMute,
}) {
  return (
    <div id="command-bar" className="w-full flex justify-center pb-6 z-20">
      <div className="bg-black/80 border border-white rounded-2xl px-10 py-4 shadow-xl flex items-center gap-10 backdrop-blur-sm">
        <button
          id="mute-btn"
          className="flex flex-col items-center hover:opacity-80 transition"
          onClick={onMute}
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 24 24"
            fill="currentColor"
            className="w-8 h-8 text-pink-400 drop-shadow-[0_0_3px_rgba(255,105,180,0.4)]"
          >
            <path d="M13.5 4.06c0-1.336-1.616-2.005-2.56-1.06l-4.5 4.5H4.508c-1.141 0-2.318.664-2.66 1.905A9.76 9.76 0 0 0 1.5 12c0 .898.121 1.768.35 2.595.341 1.24 1.518 1.905 2.659 1.905h1.93l4.5 4.5c.945.945 2.561.276 2.561-1.06V4.06ZM17.78 9.22a.75.75 0 1 0-1.06 1.06L18.44 12l-1.72 1.72a.75.75 0 1 0 1.06 1.06l1.72-1.72 1.72 1.72a.75.75 0 1 0 1.06-1.06L20.56 12l1.72-1.72a.75.75 0 1 0-1.06-1.06l-1.72 1.72-1.72-1.72Z" />
          </svg>
          <span className="text-xs text-white mt-1">Désactiver le son</span>
        </button>

        <div
          id="participants-container"
          className="flex flex-col items-center hover:opacity-80 transition cursor-pointer"
          onClick={onToggleParticipants}
        >
          <div className="relative">
            <svg
              xmlns="http://www.w3.org/2000/svg"
              viewBox="0 0 24 24"
              fill="currentColor"
              className="w-8 h-8 text-orange-400 drop-shadow-[0_0_3px_rgba(255,165,0,0.3)]"
            >
              <path d="M4.5 6.375a4.125 4.125 0 1 1 8.25 0 4.125 4.125 0 0 1-8.25 0ZM14.25 8.625a3.375 3.375 0 1 1 6.75 0 3.375 3.375 0 0 1-6.75 0ZM1.5 19.125a7.125 7.125 0 0 1 14.25 0v.003l-.001.119a.75.75 0 0 1-.363.63 13.067 13.067 0 0 1-6.761 1.873c-2.472 0-4.786-.684-6.76-1.873a.75.75 0 0 1-.364-.63l-.001-.122ZM17.25 19.128l-.001.144a2.25 2.25 0 0 1-.233.96 10.088 10.088 0 0 0 5.06-1.01.75.75 0 0 0 .42-.643 4.875 4.875 0 0 0-6.957-4.611 8.586 8.586 0 0 1 1.71 5.157v.003Z" />
            </svg>
            <div
              id="participants-count"
              className={`absolute -top-1 -right-1 bg-green-500 text-white text-xs font-bold rounded-full w-5 h-5 flex items-center justify-center shadow-lg ${
                participantsCount > 0 ? 'opacity-100' : 'opacity-0'
              }`}
            >
              {participantsCount}
            </div>
          </div>
          <span className="text-xs text-white mt-1">Participants</span>
        </div>

        <button
          id="chat-toggle-btn"
          className="flex flex-col items-center hover:opacity-80 transition"
          onClick={onToggleChat}
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 24 24"
            fill="currentColor"
            className="w-8 h-8 text-yellow-300 drop-shadow-[0_0_3px_rgba(253,224,71,0.4)]"
          >
            <path
              fillRule="evenodd"
              d="M4.804 21.644A6.707 6.707 0 0 0 6 21.75a6.721 6.721 0 0 0 3.583-1.029c.774.182 1.584.279 2.417.279 5.322 0 9.75-3.97 9.75-9 0-5.03-4.428-9-9.75-9s-9.75 3.97-9.75 9c0 2.409 1.025 4.587 2.674 6.192.232.226.277.428.254.543a3.73 3.73 0 0 1-.814 1.686.75.75 0 0 0 .44 1.223ZM8.25 10.875a1.125 1.125 0 1 0 0 2.25 1.125 1.125 0 0 0 0-2.25ZM10.875 12a1.125 1.125 0 1 1 2.25 0 1.125 1.125 0 0 1-2.25 0Zm4.875-1.125a1.125 1.125 0 1 0 0 2.25 1.125 1.125 0 0 0 0-2.25Z"
              clipRule="evenodd"
            />
          </svg>
          <span className="text-xs text-white mt-1">Ouvrir le tchat</span>
        </button>
      </div>
    </div>
  )
}
