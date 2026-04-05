import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { AppProvider } from './store';
import Layout from './components/Layout';
import Overview from './pages/Overview';
import Incidents from './pages/Incidents';
import IncidentDetail from './pages/IncidentDetail';
import Approvals from './pages/Approvals';
import Playbooks from './pages/Playbooks';
import Chat from './pages/Chat';
import Settings from './pages/Settings';

export default function App() {
  return (
    <BrowserRouter>
      <AppProvider>
        <Routes>
          <Route element={<Layout />}>
            <Route path="/" element={<Overview />} />
            <Route path="/incidents" element={<Incidents />} />
            <Route path="/incidents/:id" element={<IncidentDetail />} />
            <Route path="/approvals" element={<Approvals />} />
            <Route path="/playbooks" element={<Playbooks />} />
            <Route path="/chat" element={<Chat />} />
            <Route path="/settings" element={<Settings />} />
          </Route>
        </Routes>
      </AppProvider>
    </BrowserRouter>
  );
}
