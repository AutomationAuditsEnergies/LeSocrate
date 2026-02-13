export default function LeftSidebar() {
  return (
    <div className="fixed left-0 top-0 bottom-0 w-10 flex flex-col items-center justify-center gap-6 z-20">
      {/* Icône vidéo */}
      <button className="w-7 h-7 flex items-center justify-center rounded-md text-gray-400 hover:text-gray-700 transition-colors">
        <svg xmlns="http://www.w3.org/2000/svg" className="w-[18px] h-[18px]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
          <polygon points="23 7 16 12 23 17 23 7"></polygon>
          <rect x="1" y="5" width="15" height="14" rx="2" ry="2"></rect>
        </svg>
      </button>

      {/* Icône home */}
      <button
        onClick={() => window.location.href = '/'}
        className="w-7 h-7 flex items-center justify-center rounded-md text-gray-400 hover:text-gray-700 transition-colors"
      >
        <svg xmlns="http://www.w3.org/2000/svg" className="w-[18px] h-[18px]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
          <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"></path>
          <polyline points="9 22 9 12 15 12 15 22"></polyline>
        </svg>
      </button>

      {/* Icône lien/partage */}
      <button className="w-7 h-7 flex items-center justify-center rounded-md text-gray-400 hover:text-gray-700 transition-colors">
        <svg xmlns="http://www.w3.org/2000/svg" className="w-[18px] h-[18px]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
          <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"></path>
          <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"></path>
        </svg>
      </button>
    </div>
  )
}
