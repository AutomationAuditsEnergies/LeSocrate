export default function Sidebar({ children, className = '' }) {
  return (
    <aside
      className={`rounded-2xl border border-gray-700 bg-gray-800/90 p-6 text-gray-100 shadow-lg backdrop-blur-sm transition duration-200 hover:border-gray-600 ${className}`}
    >
      {children}
    </aside>
  )
}
