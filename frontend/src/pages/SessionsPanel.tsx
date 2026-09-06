import { useEffect, useState } from 'react';
import {
  Button,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Typography,
} from '@mui/material';
import api from '../services/api/client';

interface SessionInfo {
  id: number;
  created_at: string;
  expires_at: string;
  last_used_at: string | null;
  user_agent: string | null;
}

export default function SessionsPanel() {
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchSessions = async () => {
    setLoading(true);
    try {
      const res = await api.get<{ sessions: SessionInfo[]; count: number }>('/v1/auth/sessions');
      setSessions(res.data.sessions);
    } catch {
      setError('Failed to load sessions');
    } finally {
      setLoading(false);
    }
  };

  const revoke = async (id: number) => {
    try {
      await api.delete(`/v1/auth/sessions/${id}`);
      setSessions((prev) => prev.filter((s) => s.id !== id));
    } catch {
      setError('Failed to revoke session');
    }
  };

  useEffect(() => {
    void fetchSessions();
  }, []);

  if (loading) return <Typography>Loading sessions...</Typography>;
  if (error) return <Typography color="error">{error}</Typography>;
  if (sessions.length === 0) return <Typography>No active sessions found.</Typography>;

  return (
    <TableContainer component={Paper}>
      <Table size="small">
        <TableHead>
          <TableRow>
            <TableCell>Created</TableCell>
            <TableCell>Expires</TableCell>
            <TableCell>Last used</TableCell>
            <TableCell>Device</TableCell>
            <TableCell />
          </TableRow>
        </TableHead>
        <TableBody>
          {sessions.map((s) => (
            <TableRow key={s.id}>
              <TableCell>{new Date(s.created_at).toLocaleString()}</TableCell>
              <TableCell>{new Date(s.expires_at).toLocaleString()}</TableCell>
              <TableCell>{s.last_used_at ? new Date(s.last_used_at).toLocaleString() : '—'}</TableCell>
              <TableCell>{s.user_agent ?? '—'}</TableCell>
              <TableCell>
                <Button size="small" color="error" onClick={() => void revoke(s.id)}>
                  Revoke
                </Button>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </TableContainer>
  );
}
