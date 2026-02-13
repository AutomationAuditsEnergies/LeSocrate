export default function Header({
  userName,
  userStatus,
  title,
  avatarSrc = '/static/images/user.webp',
  onLogout,
  actions,
  wrapperClassName = 'bg-black/80 backdrop-blur-sm border border-white/30',
}) {
  return (
    <header className="relative z-10 w-full px-6 py-3">
      <div
        className={`${wrapperClassName} rounded-2xl px-4 py-3 flex items-center justify-between shadow-md`}
      >
        <div className="flex items-center gap-3">
          <img
            src={avatarSrc}
            alt="Photo utilisateur"
            className="w-10 h-10 rounded-full object-cover bg-gray-700"
          />

          <div className="text-sm text-white leading-tight">
            <div className="font-semibold">{userName}</div>
            <div className="text-xs text-gray-400">{userStatus}</div>
          </div>
        </div>

        <div className="absolute left-1/2 transform -translate-x-1/2 text-white text-2xl lemon-title text-center">
          {title}
        </div>

        <div className="flex items-center gap-3">
          {actions}
          {onLogout && (
            <button
              onClick={onLogout}
              className="flex items-center justify-center hover:opacity-90 transition"
              aria-label="Quitter"
            >
              <svg
                xmlns="http://www.w3.org/2000/svg"
                viewBox="0 0 24 24"
                fill="currentColor"
                className="w-8 h-8 text-purple-400 drop-shadow-[0_0_3px_rgba(147,51,234,0.4)]"
              >
                <path
                  fillRule="evenodd"
                  d="M7.5 3.75A1.5 1.5 0 0 0 6 5.25v13.5a1.5 1.5 0 0 0 1.5 1.5h6a1.5 1.5 0 0 0 1.5-1.5V15a.75.75 0 0 1 1.5 0v3.75a3 3 0 0 1-3 3h-6a3 3 0 0 1-3-3V5.25a3 3 0 0 1 3-3h6a3 3 0 0 1 3 3V9A.75.75 0 0 1 15 9V5.25a1.5 1.5 0 0 0-1.5-1.5h-6Zm5.03 4.72a.75.75 0 0 1 0 1.06l-1.72 1.72h10.94a.75.75 0 0 1 0 1.5H10.81l1.72 1.72a.75.75 0 1 1-1.06 1.06l-3-3a.75.75 0 0 1 0-1.06l3-3a.75.75 0 0 1 1.06 0Z"
                  clipRule="evenodd"
                />
              </svg>
            </button>
          )}
        </div>
      </div>
    </header>
  )
}
