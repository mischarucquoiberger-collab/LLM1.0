import { useState, useCallback, useMemo, Component } from 'react'
import { Toaster } from "@/components/ui/toaster"
import { QueryClientProvider } from '@tanstack/react-query'
import { queryClientInstance } from '@/lib/query-client'
import NavigationTracker from '@/lib/NavigationTracker'
import { pagesConfig } from './pages.config'
import { HashRouter as Router, Route, Routes } from 'react-router-dom';
import PageNotFound from './lib/PageNotFound';
import { AuthProvider, useAuth } from '@/lib/AuthContext';
import UserNotRegisteredError from '@/components/UserNotRegisteredError';
import PasscodeGate from '@/components/PasscodeGate';
import { CircleTransitionProvider } from '@/components/CircleTransition';
import SplashScreen, { SplashContext } from '@/components/SplashScreen';

class ErrorBoundary extends Component {
  state = { hasError: false, error: null };
  static getDerivedStateFromError(error) { return { hasError: true, error }; }
  render() {
    if (!this.state.hasError) return this.props.children;
    return (
      <div className="fixed inset-0 flex items-center justify-center bg-white text-[#0a0a0a]">
        <div className="text-center max-w-md px-6">
          <p className="text-lg font-semibold mb-2">Something went wrong</p>
          <p className="text-sm text-gray-500 mb-4">{this.state.error?.message || "Unexpected error"}</p>
          <button onClick={() => { this.setState({ hasError: false, error: null }); window.location.hash = "#/"; }}
            className="px-4 py-2 rounded-lg bg-[#0a0a0a] text-white hover:bg-gray-800 text-sm font-medium transition-colors">
            Go Home
          </button>
        </div>
      </div>
    );
  }
}

const { Pages, Layout, mainPage } = pagesConfig;
const mainPageKey = mainPage ?? Object.keys(Pages)[0];
const MainPage = mainPageKey ? Pages[mainPageKey] : () => null;

const LayoutWrapper = ({ children, currentPageName }) => Layout ?
  <Layout currentPageName={currentPageName}>{children}</Layout>
  : <>{children}</>;

const AuthenticatedApp = () => {
  const { isLoadingAuth, isLoadingPublicSettings, authError, navigateToLogin } = useAuth();

  // Show loading spinner while checking app public settings or auth
  if (isLoadingPublicSettings || isLoadingAuth) {
    return (
      <div className="fixed inset-0 flex items-center justify-center">
        <div className="w-8 h-8 border-4 border-slate-200 border-t-slate-800 rounded-full animate-spin"></div>
      </div>
    );
  }

  // Handle authentication errors
  if (authError) {
    if (authError.type === 'user_not_registered') {
      return <UserNotRegisteredError />;
    } else if (authError.type === 'auth_required') {
      navigateToLogin();
      return null;
    }
  }

  // Render the main app
  return (
    <Routes>
      <Route path="/" element={
        <LayoutWrapper currentPageName={mainPageKey}>
          <MainPage />
        </LayoutWrapper>
      } />
      {Object.entries(Pages).map(([path, Page]) => (
        <Route
          key={path}
          path={`/${path}`}
          element={
            <LayoutWrapper currentPageName={path}>
              <Page />
            </LayoutWrapper>
          }
        />
      ))}
      <Route path="*" element={<PageNotFound />} />
    </Routes>
  );
};


function App() {
  const [unlocked, setUnlocked] = useState(() => {
    try { return sessionStorage.getItem('kabu-unlocked') === '1'; } catch { return false; }
  });
  const [splashDone, setSplashDone] = useState(true); // splash disabled for now

  const handleUnlock = useCallback(() => {
    try { sessionStorage.setItem('kabu-unlocked', '1'); } catch {}
    setUnlocked(true);
  }, []);

  const splashValue = useMemo(() => ({ splashDone }), [splashDone]);
  const handleSplashDone = useCallback(() => setSplashDone(true), []);

  if (!unlocked) {
    return <PasscodeGate onUnlock={handleUnlock} />;
  }

  return (
    <ErrorBoundary>
      <AuthProvider>
        <QueryClientProvider client={queryClientInstance}>
          <SplashContext.Provider value={splashValue}>
            <Router>
              <CircleTransitionProvider>
                <NavigationTracker />
                <AuthenticatedApp />
              </CircleTransitionProvider>
            </Router>
            <Toaster />

          </SplashContext.Provider>
          {/* {!splashDone && <SplashScreen onDone={handleSplashDone} />} */}
        </QueryClientProvider>
      </AuthProvider>
    </ErrorBoundary>
  )
}

export default App
