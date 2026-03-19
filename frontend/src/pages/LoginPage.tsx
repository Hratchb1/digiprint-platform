import { useState, FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth'
import { FilmIcon, Eye, EyeOff, AlertCircle } from 'lucide-react'

export default function LoginPage() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [showPw, setShowPw] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      await login(email, password)
      navigate('/dashboard')
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Login failed. Check your credentials.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-[#0a0a0a] flex items-center justify-center px-4">
      {/* Background grain texture */}
      <div className="fixed inset-0 opacity-[0.03]"
        style={{ backgroundImage: 'url("data:image/svg+xml,%3Csvg viewBox=\'0 0 256 256\' xmlns=\'http://www.w3.org/2000/svg\'%3E%3Cfilter id=\'noise\'%3E%3CfeTurbulence type=\'fractalNoise\' baseFrequency=\'0.9\' numOctaves=\'4\' stitchTiles=\'stitch\'/%3E%3C/filter%3E%3Crect width=\'100%25\' height=\'100%25\' filter=\'url(%23noise)\' opacity=\'1\'/%3E%3C/svg%3E")', backgroundRepeat: 'repeat', backgroundSize: '128px' }}
      />

      <div className="relative w-full max-w-sm">
        {/* Card */}
        <div className="bg-[#111] border border-[#1e1e1e] rounded-2xl overflow-hidden shadow-2xl">

          {/* Orange accent bar */}
          <div className="h-[3px] bg-gradient-to-r from-[#ff6600] via-[#ff8833] to-transparent" />

          <div className="px-8 py-8">
            {/* Logo */}
            <div className="flex items-center gap-3 mb-8">
              <div className="w-10 h-10 rounded-xl bg-[#ff6600] flex items-center justify-center">
                <FilmIcon size={20} className="text-white" />
              </div>
              <div>
                <p className="text-white font-bold text-lg leading-none tracking-tight">digiPrint</p>
                <p className="text-[#444] text-xs mt-0.5 uppercase tracking-widest">Operations</p>
              </div>
            </div>

            <h1 className="text-white font-semibold text-xl mb-1">Welcome back</h1>
            <p className="text-[#555] text-sm mb-7">Sign in to your account</p>

            {error && (
              <div className="flex items-center gap-2.5 bg-[#ff444415] border border-[#ff444440] rounded-lg px-3 py-2.5 mb-5">
                <AlertCircle size={15} className="text-[#ff4444] flex-shrink-0" />
                <p className="text-[#ff4444] text-sm">{error}</p>
              </div>
            )}

            <form onSubmit={handleSubmit} className="space-y-4">
              <div>
                <label className="block text-[#888] text-xs font-medium uppercase tracking-wider mb-2">
                  Email
                </label>
                <input
                  type="email"
                  value={email}
                  onChange={e => setEmail(e.target.value)}
                  required
                  autoFocus
                  placeholder="you@digidirect.com.au"
                  className="w-full bg-[#0f0f0f] border border-[#2a2a2a] rounded-lg px-4 py-3 text-white text-sm placeholder:text-[#333] focus:outline-none focus:border-[#ff6600] transition-colors"
                />
              </div>

              <div>
                <label className="block text-[#888] text-xs font-medium uppercase tracking-wider mb-2">
                  Password
                </label>
                <div className="relative">
                  <input
                    type={showPw ? 'text' : 'password'}
                    value={password}
                    onChange={e => setPassword(e.target.value)}
                    required
                    placeholder="••••••••"
                    className="w-full bg-[#0f0f0f] border border-[#2a2a2a] rounded-lg px-4 py-3 text-white text-sm placeholder:text-[#333] focus:outline-none focus:border-[#ff6600] transition-colors pr-10"
                  />
                  <button
                    type="button"
                    onClick={() => setShowPw(!showPw)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-[#444] hover:text-[#888] transition-colors"
                  >
                    {showPw ? <EyeOff size={16} /> : <Eye size={16} />}
                  </button>
                </div>
              </div>

              <button
                type="submit"
                disabled={loading}
                className="w-full bg-[#ff6600] hover:bg-[#ff7720] disabled:opacity-50 disabled:cursor-not-allowed text-white font-semibold py-3 rounded-lg transition-colors text-sm mt-2"
              >
                {loading ? 'Signing in…' : 'Sign in'}
              </button>
            </form>
          </div>
        </div>

        <p className="text-center text-[#333] text-xs mt-6">
          digiDirect · digiPrint Operations Platform
        </p>
      </div>
    </div>
  )
}
