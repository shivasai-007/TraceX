import { Navigate, NavLink, Route, HashRouter as Router, Routes, useNavigate } from 'react-router-dom'
import { api, session } from './api/client'
import { ThemeProvider, ThemeToggle } from './theme/ThemeProvider'
import Login from './pages/Login'
import Cases from './pages/Cases'
import CaseDetail from './pages/CaseDetail'
import Investigation from './pages/Investigation'
import Entities from './pages/Entities'
import SystemStatus from './pages/SystemStatus'
import './styles/global.css'

function RequireAuth({ children }) {
  return session.token ? children : <Navigate to="/login" replace />
}

function Shell({ children }) {
  const navigate = useNavigate()
  const user = session.user

  return (
    <div className="shell">
      <aside className="rail">
        <div className="rail-brand">
          <strong>TraceX</strong>
          <span className="tiny muted">v0.1</span>
        </div>

        <nav className="rail-nav" aria-label="Main">
          <NavLink to="/cases" className={({ isActive }) => `rail-link${isActive ? ' active' : ''}`}>
            Cases
          </NavLink>
          <NavLink to="/entities" className={({ isActive }) => `rail-link${isActive ? ' active' : ''}`}>
            Entity intelligence
          </NavLink>
          <NavLink to="/status" className={({ isActive }) => `rail-link${isActive ? ' active' : ''}`}>
            System status
          </NavLink>
        </nav>

        <div className="grow rail-section" />

        <div className="rail-section stack" style={{ gap: 'var(--space-3)' }}>
          <div>
            <div className="rail-section-title">Signed in</div>
            <div className="small">{user?.name}</div>
          </div>
          <div className="row" style={{ gap: 'var(--space-2)' }}>
            <ThemeToggle />
            <button
              className="btn btn-quiet btn-sm"
              onClick={() => {
                session.clear()
                navigate('/login')
              }}
            >
              Sign out
            </button>
          </div>
        </div>
      </aside>

      <main className="main">{children}</main>
    </div>
  )
}

export default function App() {
  return (
    <ThemeProvider>
      <Router>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route
            path="/cases"
            element={<RequireAuth><Shell><Cases /></Shell></RequireAuth>}
          />
          <Route
            path="/cases/:caseId"
            element={<RequireAuth><Shell><CaseDetail /></Shell></RequireAuth>}
          />
          <Route
            path="/investigations/:investigationId"
            element={<RequireAuth><Shell><Investigation /></Shell></RequireAuth>}
          />
          <Route
            path="/entities"
            element={<RequireAuth><Shell><Entities /></Shell></RequireAuth>}
          />
          <Route
            path="/status"
            element={<RequireAuth><Shell><SystemStatus /></Shell></RequireAuth>}
          />
          <Route path="*" element={<Navigate to={session.token ? '/cases' : '/login'} replace />} />
        </Routes>
      </Router>
    </ThemeProvider>
  )
}
