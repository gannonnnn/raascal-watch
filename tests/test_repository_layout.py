"""Guard the configuration-file placement that previously broke fresh clones."""
from pathlib import Path
import shutil
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_setup_templates_are_at_repository_root():
    for name in ('.env.example', '.gitignore'):
        assert (ROOT/name).is_file(), f'{name} must be at the repository root'
        assert not (ROOT/'raascal_watch/templates'/name).exists()
    assert (ROOT/'start-raascal-watch.command').is_file()
    assert (ROOT/'config/watchlist.defaults.yaml').is_file()


def test_git_actually_ignores_local_secrets_and_database(tmp_path):
    git = shutil.which('git')
    if not git:
        pytest.skip('git is not installed on this test host')
    subprocess.run([git,'init','-q',str(tmp_path)],check=True)
    shutil.copyfile(ROOT/'.gitignore',tmp_path/'.gitignore')
    for name in ('.env', '.venv/private.txt', 'data/raascal_watch.db', 'data/raascal_watch.db-wal'):
        target=tmp_path/name
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text('fixture only')
        assert subprocess.run([git,'check-ignore','-q',name],cwd=tmp_path).returncode==0, name
    (tmp_path/'.env.example').write_text('SAFE_TEMPLATE=')
    assert subprocess.run([git,'check-ignore','-q','.env.example'],cwd=tmp_path).returncode==1
