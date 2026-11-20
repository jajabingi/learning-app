import { lazy, Suspense } from 'react'
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { useAuth } from './contexts/auth'
import { Layout } from './components/Layout'
import { Loading } from './components/ui'
import { AuthPage } from './pages/Auth'
import Dashboard from './pages/Dashboard'
import LibraryPage from './pages/Library'
import QuestionsPage from './pages/Questions'
import QuestionEditPage from './pages/QuestionEdit'
import StudySetup from './pages/StudySetup'
import ReviewQueue from './pages/ReviewQueue'
import NotesPage from './pages/Notes'
import SettingsPage from './pages/Settings'
import { CoursesList, TeachDashboard } from './pages/teach/Courses'
import CourseEditor from './pages/teach/CourseEditor'
import LessonEditor from './pages/teach/LessonEditor'
import CoursePreview from './pages/teach/Preview'
import Team from './pages/teach/Team'
import Institutions from './pages/teach/Institutions'
import { StudentProfile, StudentsList } from './pages/teach/Students'
import { PracticeHome, PracticeSet } from './pages/student/Practice'
import { MyCourses, StudentAccount, StudentCourse, StudentHome, StudentLayout } from './pages/student/Portal'
import { ExploreAll, ExploreInstitution, Landing, PublicCourse, PublicLayout } from './pages/public/Public'

// Heavier pages (charts, graph, study runner) load on demand.
const StudySession = lazy(() => import('./pages/StudySession'))
const GraphPage = lazy(() => import('./pages/Graph'))
const AnalyticsPage = lazy(() => import('./pages/Analytics'))

function Protected({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth()
  const loc = useLocation()
  if (loading) return <Loading />
  if (!user) return <Navigate to="/login" replace state={{ from: loc.pathname + loc.search }} />
  return <>{children}</>
}

/** Teacher/admin only (UI convenience — every API call is authorised again on the server). */
function StaffOnly({ children, admin }: { children: React.ReactNode; admin?: boolean }) {
  const { user } = useAuth()
  if (!user || user.role === 'student' || (admin && user.role !== 'admin')) return <Navigate to="/" replace />
  return <>{children}</>
}

function RedirectToLogin() {
  const loc = useLocation()
  return <Navigate to="/login" replace state={{ from: loc.pathname + loc.search }} />
}

/** The site root is ALWAYS the public home page (landing). Signed-in users reach their area from the header button. */
const publicRoutes = (
  <Route element={<PublicLayout />}>
    <Route index element={<Landing />} />
    <Route path="explore" element={<ExploreAll />} />
    <Route path="explore/:slug" element={<ExploreInstitution />} />
    <Route path="course/:id" element={<PublicCourse />} />
  </Route>
)

export default function App() {
  const { user, loading } = useAuth()
  if (loading) return <Loading /> // wait until we know the role, otherwise deep links get redirected by the wrong route tree
  if (!user) {
    return (
      <Suspense fallback={<Loading />}>
        <Routes>
          <Route path="/login" element={<AuthPage mode="login" />} />
          <Route path="/register" element={<AuthPage mode="register" />} />
          <Route path="/teachers" element={<AuthPage mode="login" staff />} />
          {publicRoutes}
          <Route path="*" element={<RedirectToLogin />} />
        </Routes>
      </Suspense>
    )
  }
  if (user.role === 'student') {
    return (
      <Suspense fallback={<Loading />}>
        <Routes>
          <Route path="/login" element={<AuthPage mode="login" />} />
          <Route path="/register" element={<AuthPage mode="register" />} />
          <Route path="/teachers" element={<AuthPage mode="login" staff />} />
          {publicRoutes}
          <Route element={<StudentLayout />}>
            <Route path="my" element={<StudentHome />} />
            <Route path="courses" element={<MyCourses />} />
            <Route path="courses/:id" element={<StudentCourse />} />
            <Route path="practice" element={<PracticeHome />} />
            <Route path="practice/:id" element={<PracticeSet />} />
            <Route path="account" element={<StudentAccount />} />
          </Route>
          <Route path="*" element={<Navigate to="/my" replace />} />
        </Routes>
      </Suspense>
    )
  }
  return (
    <Suspense fallback={<Loading />}>
      <Routes>
        <Route path="/login" element={<AuthPage mode="login" />} />
        <Route path="/register" element={<AuthPage mode="register" />} />
        <Route path="/teachers" element={<AuthPage mode="login" staff />} />
        {publicRoutes}
        <Route element={<Layout />}>
          <Route path="dashboard" element={<StaffOnly><Dashboard /></StaffOnly>} />
          <Route path="teach" element={<StaffOnly><TeachDashboard /></StaffOnly>} />
          <Route path="teach/courses" element={<StaffOnly><CoursesList /></StaffOnly>} />
          <Route path="teach/courses/:id" element={<StaffOnly><CourseEditor /></StaffOnly>} />
          <Route path="teach/courses/:id/preview" element={<StaffOnly><CoursePreview /></StaffOnly>} />
          <Route path="teach/courses/:id/lessons/:lid" element={<StaffOnly><LessonEditor /></StaffOnly>} />
          <Route path="teach/institutions" element={<StaffOnly><Institutions /></StaffOnly>} />
          <Route path="teach/students" element={<StaffOnly><StudentsList /></StaffOnly>} />
          <Route path="teach/students/:id" element={<StaffOnly><StudentProfile /></StaffOnly>} />
          <Route path="teach/team" element={<StaffOnly admin><Team /></StaffOnly>} />
          <Route path="library/*" element={<LibraryPage />} />
          <Route path="questions" element={<QuestionsPage />} />
          <Route path="questions/:id" element={<QuestionEditPage />} />
          <Route path="study" element={<StudySetup />} />
          <Route path="review" element={<ReviewQueue />} />
          <Route path="graph" element={<GraphPage />} />
          <Route path="notes" element={<NotesPage />} />
          <Route path="notes/:id" element={<NotesPage />} />
          <Route path="analytics" element={<AnalyticsPage />} />
          <Route path="settings" element={<SettingsPage />} />
        </Route>
        {/* Study session is full-screen and distraction free: no sidebar */}
        <Route path="study/session/:id" element={<StudySession />} />
        <Route path="*" element={<Navigate to="/teach" replace />} />
      </Routes>
    </Suspense>
  )
}
