import { useEffect } from 'react'
import { Page } from '@/sections/Page'
import './Landing.css'

export default function Landing() {
  useEffect(() => {
    document.documentElement.classList.add('limova-landing-active')
    document.body.classList.add('limova-landing-active')

    return () => {
      document.documentElement.classList.remove('limova-landing-active')
      document.body.classList.remove('limova-landing-active')
    }
  }, [])

  return (
    <div className="limova-strict-copy font-geist">
      <Page />
    </div>
  )
}
