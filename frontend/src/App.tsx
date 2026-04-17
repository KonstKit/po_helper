import { useEffect, useState, Suspense, lazy } from 'react';
import { Routes, Route, Navigate, useNavigate } from 'react-router-dom';
import { useDispatch, useSelector } from 'react-redux';
import { Box, CircularProgress } from '@mui/material';
import { AppDispatch, RootState } from './store/store';
import { logout } from './store/authSlice';
import { initializeAppData } from './store/dataThunks';
import { storage } from './utils/storage';
import { isDevelopment } from './utils/env';
import { analytics } from './services/analytics';
import { generateSmartDefaults, saveSmartDefaults } from './utils/smartDefaults';
import Layout from './components/Layout';
import BackendStatusAlert from './components/BackendStatusAlert';
import RequireAuth from './components/RequireAuth';
import OnboardingWizard from './components/OnboardingWizard';
import { PageViewTracker } from './components/PageViewTracker';
import { ToastProvider } from './components/ToastProvider';
import { logError } from './utils/errorUtils';
import './App.css';

const Dashboard = lazy(() => import('./pages/Dashboard'));
const Projects = lazy(() => import('./pages/Projects'));
const ProjectDetail = lazy(() => import('./pages/ProjectDetail'));
const Tasks = lazy(() => import('./pages/Tasks'));
const Analytics = lazy(() => import('./pages/Analytics'));
const Settings = lazy(() => import('./pages/Settings'));
const Profile = lazy(() => import('./pages/Profile'));
const Login = lazy(() => import('./pages/Login'));
const Knowledge = lazy(() => import('./pages/Knowledge'));
const Quality = lazy(() => import('./pages/Quality'));
const Testing = lazy(() => import('./pages/Testing'));
const JiraFieldsConfig = lazy(() => import('./pages/JiraFieldsConfig'));
const Traceability = lazy(() => import('./pages/Traceability'));
const TraceabilityFlowBuilder = lazy(() => import('./pages/TraceabilityFlowBuilder'));
const TraceabilityExecutionHistory = lazy(() => import('./pages/TraceabilityExecutionHistory'));
const TraceabilityVisualization = lazy(() => import('./pages/TraceabilityVisualization'));
const SprintCapacity = lazy(() => import('./pages/SprintCapacity'));

const LazyFallback = () => (
  <Box
    sx={{
      minHeight: '60vh',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      width: '100%',
    }}
  >
    <CircularProgress />
  </Box>
);

function App() {
  const dispatch = useDispatch<AppDispatch>();
  const navigate = useNavigate();
  const isAuthenticated = useSelector((state: RootState) => state.auth.isAuthenticated);
  const [onboardingDismissed, setOnboardingDismissed] = useState(false);

  useEffect(() => {
    // Clean up expired cache on startup
    storage.clearExpired();
    if (isDevelopment) {
      storage.getUsageInfo();
    }

    // Track account creation or first login
    const accountCreated = localStorage.getItem('account_created_at');
    if (!accountCreated) {
      localStorage.setItem('account_created_at', Date.now().toString());
      analytics.trackTimeToValue('accountCreatedAt');
    }

    // Track first login
    const firstLogin = localStorage.getItem('first_login_at');
    if (!firstLogin) {
      localStorage.setItem('first_login_at', Date.now().toString());
      analytics.trackTimeToValue('firstLoginAt');
    }

    // Track session
    analytics.track('app_loaded');
  }, []);

  const showOnboarding = isAuthenticated
    && !localStorage.getItem('onboarding_completed')
    && !onboardingDismissed;

  useEffect(() => {
    if (!isAuthenticated) {
      return;
    }

    // Initialize app data once authentication is confirmed
    dispatch(initializeAppData());
  }, [dispatch, isAuthenticated]);

  useEffect(() => {
    const handleAuthError = () => {
      dispatch(logout());
      navigate('/login');
    };

    const listener = () => handleAuthError();
    window.addEventListener('auth-error', listener);

    return () => {
      window.removeEventListener('auth-error', listener);
    };
  }, [dispatch, navigate]);

  const handleOnboardingComplete = async () => {
    setOnboardingDismissed(true);

    // Generate and save smart defaults after onboarding
    try {
      const defaults = await generateSmartDefaults();
      saveSmartDefaults(defaults);
    } catch (error) {
      logError('Failed to generate smart defaults', error);
    }

    navigate('/');
  };

  const handleOnboardingSkip = () => {
    localStorage.setItem('onboarding_completed', 'true');
    setOnboardingDismissed(true);
  };

  return (
    <ToastProvider>
      <BackendStatusAlert />
      <OnboardingWizard
        open={showOnboarding}
        onComplete={handleOnboardingComplete}
        onSkip={handleOnboardingSkip}
      />
      <PageViewTracker>
        <Suspense fallback={<LazyFallback />}>
          <Routes>
            <Route
              path="/login"
              element={isAuthenticated ? <Navigate to="/" replace /> : <Login />}
            />
            <Route
              path="/"
              element={(
                <RequireAuth>
                  <Layout />
                </RequireAuth>
              )}
            >
              <Route index element={<Dashboard />} />
              <Route path="projects" element={<Projects />} />
              <Route path="projects/:id" element={<ProjectDetail />} />
              <Route path="tasks" element={<Tasks />} />
              <Route path="analytics" element={<Analytics />} />
              <Route path="knowledge" element={<Knowledge />} />
              <Route path="quality" element={<Quality />} />
              <Route path="testing" element={<Testing />} />
              <Route path="settings" element={<Settings />} />
              <Route path="jira-fields" element={<JiraFieldsConfig />} />
              <Route path="traceability" element={<Traceability />} />
              <Route path="traceability/flow-builder" element={<TraceabilityFlowBuilder />} />
              <Route path="traceability/history" element={<TraceabilityExecutionHistory />} />
              <Route path="traceability/visualization" element={<TraceabilityVisualization />} />
              <Route path="sprint-capacity" element={<SprintCapacity />} />
              <Route path="profile" element={<Profile />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Route>
          </Routes>
        </Suspense>
      </PageViewTracker>
    </ToastProvider>
  );
}

export default App;
