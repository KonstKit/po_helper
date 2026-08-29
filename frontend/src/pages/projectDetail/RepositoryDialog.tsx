import {
  Alert,
  Checkbox,
  Divider,
  FormControl,
  InputLabel,
  Select,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  LinearProgress,
  MenuItem,
  Stack,
  TextField,
  Typography,
} from "@mui/material";

import type { SelectChangeEvent } from "@mui/material/Select";

import type { RepositoryProvider } from "../../services/api";
import type { useProjectRepositories } from "./useProjectRepositories";

type RepoState = ReturnType<typeof useProjectRepositories>;

/** Link-Repository dialog (extracted from ProjectDetail, E6). */
export const RepositoryDialog = ({ repo }: { repo: RepoState }) => {
  return (
        <Dialog open={repo.repoDialogOpen} onClose={repo.handleRepoDialogClose}>
          <DialogTitle>Link Repository</DialogTitle>
          <DialogContent sx={{ width: 420, maxWidth: '100%' }}>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
              Add a GitHub or GitLab repository to associate pull requests and commits with this project.
            </Typography>
            {!repo.repoProviders.github && !repo.repoProviders.gitlab && (
              <Alert severity="warning" sx={{ mb: 2 }}>
                Configure a GitHub or GitLab integration first to enable API lookups for repositories.
              </Alert>
            )}
            <TextField
              fullWidth
              label="Repository URL"
              placeholder="https://github.com/org/repo"
              value={repo.repoForm.repositoryUrl}
              onChange={(e) =>
                repo.setRepoForm((form) => ({
                  ...form,
                  repositoryUrl: e.target.value,
                }))
              }
              margin="dense"
              disabled={repo.repoSaving}
            />
            <Divider sx={{ my: 2 }}>or</Divider>
            <FormControl fullWidth margin="dense" disabled={repo.repoSaving}>
              <InputLabel id="repo-provider-label">Provider</InputLabel>
              <Select
                labelId="repo-provider-label"
                label="Provider"
                value={repo.repoForm.provider}
                onChange={(e: SelectChangeEvent<RepositoryProvider>) => {
                  const nextProvider = e.target.value;
                  if (nextProvider !== 'github' && nextProvider !== 'gitlab') {
                    return;
                  }
                  repo.setRepoForm((form) => ({
                    ...form,
                    provider: nextProvider,
                  }));
                }}
              >
                <MenuItem value="github" disabled={!repo.repoProviders.github}>GitHub</MenuItem>
                <MenuItem value="gitlab" disabled={!repo.repoProviders.gitlab}>GitLab</MenuItem>
              </Select>
            </FormControl>
            <TextField
              fullWidth
              label="Repository Slug"
              placeholder="org/repo"
              value={repo.repoForm.repoSlug}
              onChange={(e) =>
                repo.setRepoForm((form) => ({
                  ...form,
                  repoSlug: e.target.value,
                }))
              }
              helperText="Used when repository URL is not provided."
              margin="dense"
              disabled={repo.repoSaving}
            />




{repo.repoForm.provider === 'gitlab' && repo.repoProviders.gitlab && (

  <Box sx={{ mt: 2 }}>

    <Divider sx={{ mb: 2 }}>GitLab project browser</Divider>

    <Stack spacing={1}>

      <TextField

        label="Group path"

        placeholder="company/platform"

        value={repo.gitlabGroupPath}

        onChange={(event) => {

          repo.setGitlabGroupPath(event.target.value);

        }}

        size="small"

        disabled={repo.gitlabLoading}

      />

      <TextField

        label="Search"

        placeholder="project name"

        value={repo.gitlabSearch}

        onChange={(event) => {

          repo.setGitlabSearch(event.target.value);

        }}

        size="small"

        disabled={repo.gitlabLoading}

      />

      <Stack direction="row" spacing={1}>

        <Button

          size="small"

          variant="contained"

          onClick={() => void repo.performGitlabSearch(1)}

          disabled={repo.gitlabLoading}

        >

          Search

        </Button>

        <Button

          size="small"

          onClick={() => {

            repo.setGitlabGroupPath('');

            repo.setGitlabSearch('');

            repo.resetGitlabResults();

          }}

          disabled={repo.gitlabLoading}

        >

          Clear

        </Button>

      </Stack>

    </Stack>



    {repo.gitlabError && (

      <Alert severity="error" sx={{ mt: 1 }}>

        {repo.gitlabError}

      </Alert>

    )}



    <Box sx={{ mt: 2, maxHeight: 220, overflowY: 'auto', position: 'relative' }}>

      {repo.gitlabLoading && <LinearProgress sx={{ position: 'sticky', top: 0 }} />}

      <Table size="small">

        <TableHead>

          <TableRow>

            <TableCell>Name</TableCell>

            <TableCell>Slug</TableCell>

            <TableCell align="right">Select</TableCell>

          </TableRow>

        </TableHead>

        <TableBody>

          {repo.gitlabProjects.map((project) => (

            <TableRow key={project.id} hover>

              <TableCell>

                <Typography variant="body2" fontWeight={600}>

                  {project.name}

                </Typography>

                <Typography variant="caption" color="text.secondary">

                  {project.path_with_namespace}

                </Typography>

              </TableCell>

              <TableCell>{project.path_with_namespace}</TableCell>

              <TableCell align="right">

                <Button

                  size="small"

                  onClick={() => {

                    repo.setRepoForm((form) => ({

                      ...form,

                      provider: 'gitlab',

                      repoSlug: project.path_with_namespace || form.repoSlug,

                      repositoryUrl: project.http_url_to_repo || form.repositoryUrl,

                    }));

                  }}

                >

                  Use

                </Button>

              </TableCell>

            </TableRow>

          ))}

          {!repo.gitlabLoading && repo.gitlabProjects.length === 0 && (

            <TableRow>

              <TableCell colSpan={3}>

                <Typography variant="body2" color="text.secondary">

                  No projects found. Adjust filters to try again.

                </Typography>

              </TableCell>

            </TableRow>

          )}

        </TableBody>

      </Table>

      {repo.gitlabHasNextPageRef.current && (

        <Box sx={{ display: 'flex', justifyContent: 'center', py: 1 }}>

          <Button

            size="small"

            onClick={() => repo.performGitlabSearch(repo.gitlabPage + 1, { append: true })}

            disabled={repo.gitlabLoading}

          >

            Load more

          </Button>

        </Box>

      )}

    </Box>

  </Box>

)}

            <FormControlLabel
              control={
                <Checkbox
                  checked={repo.repoForm.isPrimary}
                  onChange={(e) =>
                    repo.setRepoForm((form) => ({
                      ...form,
                      isPrimary: e.target.checked,
                    }))
                  }
                  disabled={repo.repoSaving}
                />
              }
              label="Set as primary repository"
              sx={{ mt: 1 }}
            />
            {repo.repoError && (
              <Alert severity="error" sx={{ mt: 2 }}>
                {repo.repoError}
              </Alert>
            )}
          </DialogContent>
          <DialogActions>
            <Button onClick={repo.handleRepoDialogClose} disabled={repo.repoSaving}>
              Cancel
            </Button>
            <Button
              onClick={repo.handleRepoSubmit}
              variant="contained"
              disabled={
                repo.repoSaving ||
                (!repo.repoForm.repositoryUrl.trim() && !repo.repoForm.repoSlug.trim())
              }
            >
              {repo.repoSaving ? "Linking..." : "Link Repository"}
            </Button>
          </DialogActions>
        </Dialog>
  );
};

export default RepositoryDialog;
