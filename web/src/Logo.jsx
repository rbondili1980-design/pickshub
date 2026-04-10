export function PicksHubIcon({ size = 32, className = '' }) {
  const id = `ph-grad-${size}`
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none" className={className} aria-label="PicksHub">
      <defs>
        <linearGradient id={id} x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor="#6366f1" />
          <stop offset="100%" stopColor="#8b5cf6" />
        </linearGradient>
      </defs>
      <rect width="32" height="32" rx="8" fill={`url(#${id})`} />
      {/* Outer ring */}
      <circle cx="16" cy="16" r="8.5" stroke="white" strokeWidth="1.5" strokeOpacity="0.35" fill="none" />
      {/* Inner ring */}
      <circle cx="16" cy="16" r="4.5" stroke="white" strokeWidth="1.5" strokeOpacity="0.65" fill="none" />
      {/* Checkmark */}
      <path d="M10.5 16.5 L14.5 20.5 L21.5 11.5" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

export function PicksHubWordmark({ iconSize = 28, textSize = 'text-xl', className = '' }) {
  return (
    <div className={`flex items-center gap-2.5 ${className}`}>
      <PicksHubIcon size={iconSize} />
      <span className={`font-extrabold tracking-tight text-gray-900 dark:text-white ${textSize}`}>
        Picks<span className="text-indigo-500">Hub</span>
      </span>
    </div>
  )
}
