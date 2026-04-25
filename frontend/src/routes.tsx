import { Routes, Route, Navigate, useParams } from 'react-router-dom';
import { OverviewView } from './views/OverviewView';
import { AgileView } from './views/AgileView';
import { PlansView } from './views/PlansView';
import { WorkflowView } from './views/WorkflowView';
import { PicksView } from './views/PicksView';
import { IdeationView } from './views/IdeationView';
import { DebugView } from './views/DebugView';
import { DesignView } from './views/DesignView';
import { DocumentsView } from './views/DocumentsView';
import { IntentsView } from './views/IntentsView';
import { FactCheckView } from './views/FactCheckView';
import { ReferenceView } from './views/ReferenceView';
import { SettingsView } from './views/SettingsView';
import { ArchivesView } from './views/ArchivesView';
import { FlowView } from './views/FlowView';

function IntentLegacyRedirect() {
  const { intentId } = useParams();
  return <Navigate to={intentId ? `/memory/intents/${intentId}` : '/memory/intents'} replace />;
}

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<Navigate to="/overview" replace />} />
      <Route path="/overview" element={<OverviewView />} />
      <Route path="/agile" element={<AgileView />} />
      <Route path="/agile/:agiId" element={<AgileView />} />
      <Route path="/agile/:agiId/objective" element={<AgileView />} />
      <Route path="/agile/:agiId/flow" element={<FlowView />} />
      <Route path="/plans" element={<PlansView />} />
      <Route path="/plans/:planId" element={<PlansView />} />
      <Route path="/plans/:planId/tasks" element={<PlansView />} />
      <Route path="/workflow" element={<WorkflowView />} />
      <Route path="/workflow/:reqId" element={<WorkflowView />} />
      <Route path="/workflow/:reqId/spec" element={<WorkflowView />} />
      <Route path="/workflow/:reqId/tasks/:taskId" element={<WorkflowView />} />
      <Route path="/picks" element={<PicksView />} />
      <Route path="/picks/:captureId" element={<PicksView />} />
      <Route path="/ideation" element={<IdeationView />} />
      <Route path="/ideation/:sessionId" element={<IdeationView />} />
      <Route path="/debug" element={<DebugView />} />
      <Route path="/debug/:sessionId" element={<DebugView />} />
      <Route path="/designs" element={<DesignView />} />
      <Route path="/designs/:designId" element={<DesignView />} />
      <Route path="/documents" element={<DocumentsView />} />
      <Route path="/intents" element={<Navigate to="/memory/intents" replace />} />
      <Route path="/intents/:intentId" element={<IntentLegacyRedirect />} />
      <Route path="/memory/intents" element={<IntentsView />} />
      <Route path="/memory/intents/:intentId" element={<IntentsView />} />
      <Route path="/memory/fact-checks" element={<FactCheckView />} />
      <Route path="/memory/fact-checks/:fcId" element={<FactCheckView />} />
      <Route path="/memory/references" element={<ReferenceView />} />
      <Route path="/memory/references/:refId" element={<ReferenceView />} />
      <Route path="/archives" element={<ArchivesView />} />
      <Route path="/settings" element={<SettingsView />} />
      <Route path="*" element={<Navigate to="/overview" replace />} />
    </Routes>
  );
}
