import { useEffect, useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Building2, ClipboardCheck, BarChart3, BookOpenText, GraduationCap as TeachIcon, Users as TeamIcon, CalendarClock, FileText, GraduationCap, HelpCircle, LayoutDashboard, Library, LogOut, Menu as MenuIcon, ShieldCheck, Moon, Network, Search, Settings, Sun, X } from 'lucide-react'
import { get } from '@/api/client'
import { useAuth } from '@/contexts/auth'
import { useTheme } from '@/contexts/theme'
import { QuickCreateMenu, QuickCreateProvider } from './QuickCreate'
import { SearchPalette } from './SearchPalette'
import { cx } from './ui'
import { tt } from '@/i18n'


const TEACH_NAV = [
  { to: '/teach', label: tt("Teaching"), Icon: TeachIcon, end: true },
  { to: '/teach/courses', label: tt("Courses"), Icon: BookOpenText },
  { to: '/teach/exams', label: tt("Exams"), Icon: ClipboardCheck },
  { to: '/teach/institutions', label: tt("Institutions"), Icon: Building2 },
  { to: '/teach/students', label: tt("Students"), Icon: TeamIcon },
]
const NAV = [
  { to: '/dashboard', label: tt("Dashboard"), Icon: LayoutDashboard, end: true },
  { to: '/library', label: tt("Knowledge Library"), Icon: Library },
  { to: '/questions', label: tt("Questions"), Icon: HelpCircle },
  { to: '/study', label: tt("Study"), Icon: GraduationCap },
  { to: '/review', label: tt("Review Queue"), Icon: CalendarClock, badge: true },
  { to: '/graph', label: tt("Knowledge Graph"), Icon: Network },
  { to: '/notes', label: tt("Notes"), Icon: FileText },
  { to: '/analytics', label: tt("Analytics"), Icon: BarChart3 },
  { to: '/settings', label: tt("Settings"), Icon: Settings },
]

function Brand() {
  return (
    <div className="flex items-center gap-2 px-3 py-4">
      <div className="flex h-7 w-7 items-center justify-center rounded-md bg-accent text-accent-fg"><BookOpenText size={16} /></div>
      <span className="text-[15px] font-semibold tracking-tight">{tt("Recall")}</span>
    </div>
  )
}

function NavList({ onNavigate, due, admin }: { onNavigate?(): void; due: number; admin?: boolean }) {
  const item = ({ to, label, Icon, end, badge }: { to: string; label: string; Icon: typeof Search; end?: boolean; badge?: boolean }) => (
    <NavLink key={to} to={to} end={end} onClick={onNavigate} className={({ isActive }) => cx('flex h-9 items-center gap-2.5 rounded px-2.5 text-sm font-medium', isActive ? 'bg-raised text-fg' : 'text-muted hover:bg-raised hover:text-fg')}>
      <Icon size={16} /><span className="flex-1">{label}</span>
      {badge && due > 0 && <span className="tabnum rounded-full bg-accent px-1.5 text-xs font-semibold text-accent-fg">{due > 99 ? '99+' : due}</span>}
    </NavLink>
  )
  return (
    <nav className="flex-1 space-y-0.5 overflow-y-auto px-2" aria-label={tt("Main")}>
      <div className="px-2.5 pb-1 pt-1 text-[11px] font-semibold uppercase tracking-wide text-faint">{tt("Teaching")}</div>
      {TEACH_NAV.map(item)}
      {admin && item({ to: '/admin', label: tt("Admin dashboard"), Icon: ShieldCheck, end: true })}
      {admin && item({ to: '/admin/users', label: tt("Users"), Icon: TeamIcon })}
      {admin && item({ to: '/teach/team', label: tt("Team & permissions"), Icon: TeamIcon })}
      <div className="px-2.5 pb-1 pt-4 text-[11px] font-semibold uppercase tracking-wide text-faint">{tt("Personal workspace")}</div>
      {NAV.map(({ to, label, Icon, end, badge }) => (
        <NavLink key={to} to={to} end={end} onClick={onNavigate} className={({ isActive }) => cx('flex h-9 items-center gap-2.5 rounded px-2.5 text-sm font-medium', isActive ? 'bg-raised text-fg' : 'text-muted hover:bg-raised hover:text-fg')}>
          <Icon size={16} />
          <span className="flex-1">{label}</span>
          {badge && due > 0 && <span className="tabnum rounded-full bg-accent px-1.5 text-xs font-semibold text-accent-fg">{due > 99 ? '99+' : due}</span>}
        </NavLink>
      ))}
    </nav>
  )
}

export function Layout() {
  const { user, logout } = useAuth()
  const { dark, setPref } = useTheme()
  const [drawer, setDrawer] = useState(false)
  const [search, setSearch] = useState(false)
  const loc = useLocation()
  const nav = useNavigate()
  const due = useQuery({ queryKey: ['due-badge'], queryFn: () => get<{ due_now: number }>('/review/queue', { limit: 1 }), refetchInterval: 60_000 })

  useEffect(() => setDrawer(false), [loc.pathname])
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); setSearch(true) }
    }
    document.addEventListener('keydown', h)
    return () => document.removeEventListener('keydown', h)
  }, [])

  const dueCount = due.data?.due_now ?? 0
  const sidebar = (
    <div className="flex h-full flex-col">
      <Brand />
      <NavList due={dueCount} admin={user?.role === "admin"} onNavigate={() => setDrawer(false)} />
      <div className="border-t border-line p-2">
        <div className="mb-1 truncate px-2.5 text-xs text-muted" title={user?.email}>{user?.display_name || user?.email}</div>
        <button className="flex h-9 w-full items-center gap-2.5 rounded px-2.5 text-sm text-muted hover:bg-raised hover:text-fg" onClick={() => { logout(); nav('/login') }}>
          <LogOut size={16} /> {tt("Sign out")}
        </button>
      </div>
    </div>
  )

  return (
    <QuickCreateProvider>
      <div className="flex h-full">
        <aside className="hidden w-60 shrink-0 border-e border-line bg-surface lg:block">{sidebar}</aside>
        {drawer && (
          <div className="fixed inset-0 z-40 lg:hidden" role="dialog" aria-modal="true" aria-label={tt("Navigation")}>
            <div className="absolute inset-0 bg-black/40" onClick={() => setDrawer(false)} />
            <aside className="absolute inset-y-0 start-0 w-72 max-w-[85%] bg-surface shadow-xl">
              <button className="btn btn-ghost btn-icon absolute end-2 top-3" aria-label={tt("Close menu")} onClick={() => setDrawer(false)}><X size={16} /></button>
              {sidebar}
            </aside>
          </div>
        )}
        <div className="flex min-w-0 flex-1 flex-col">
          <header className="flex h-12 shrink-0 items-center gap-2 border-b border-line bg-surface px-3 sm:px-5">
            <button className="btn btn-ghost btn-icon lg:hidden" aria-label={tt("Open menu")} onClick={() => setDrawer(true)}><MenuIcon size={18} /></button>
            <button onClick={() => setSearch(true)} className="flex h-8 min-w-0 max-w-md flex-1 items-center gap-2 rounded border border-line bg-bg px-2.5 text-start text-sm text-faint hover:border-faint" aria-label={tt("Search")}>
              <Search size={14} /> <span className="flex-1 truncate">{tt("Search everything…")}</span>
              <kbd className="hidden rounded border border-line px-1 text-[11px] sm:inline">Ctrl K</kbd>
            </button>
            <div className="ml-auto flex items-center gap-1">
              <QuickCreateMenu />
              <button className="btn btn-ghost btn-icon" aria-label={dark ? tt("Switch to light mode") : tt("Switch to dark mode")} onClick={() => setPref(dark ? 'light' : 'dark')}>
                {dark ? <Sun size={16} /> : <Moon size={16} />}
              </button>
            </div>
          </header>
          <main className="flex-1 overflow-y-auto" id="main">
            <Outlet />
          </main>
        </div>
      </div>
      <SearchPalette open={search} onClose={() => setSearch(false)} />
    </QuickCreateProvider>
  )
}

export function Page({ children, narrow, className }: { children: React.ReactNode; narrow?: boolean; className?: string }) {
  return <div className={cx('mx-auto w-full px-4 py-5 sm:px-6 sm:py-6', narrow ? 'max-w-3xl' : 'max-w-6xl', className)}>{children}</div>
}
