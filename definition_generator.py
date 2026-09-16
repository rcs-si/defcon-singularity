"""Render dependency plans as Singularity definitions without writing files."""

from pathlib import Path
import shlex
from typing import Mapping

from dependency_resolver import DependencyPlan
from environments.conda import prepare_environment as prepare_conda_environment
from environments.modules import runtime_paths
from path_utils import _path_is_under

DEF_TEMPLATE = """\
Bootstrap: localimage
From: {singularity_image}

%files
{files_section}

%setup
    # rsync -rL dereferences cyclic symlinks that break %%files cp -r
{rsync_section}

%post
    # This disables the module command, as all of the variables
    # set by Lmod are captured in the environment section. 
    # This way the original job script (with "module load" commands)
    # can run without modification.
    cat > /usr/local/bin/module << 'EOF'
#!/bin/sh
exit 0
EOF
    chmod +x /usr/local/bin/module
    
    
%environment
{env_section}

%runscript
    exec /bin/bash "$@"
"""


def _shell_quote(value: str) -> str:
    return shlex.quote(value)


def prepare_environment(plan: DependencyPlan, env_vars: Mapping[str, str]) -> dict:
    """Build container search paths without changing the captured environment."""
    result, conda_bins = prepare_conda_environment(env_vars, plan.conda_roots)
    module_bins, module_libs, all_lib_dirs = runtime_paths(
        plan.module_roots, plan.conda_roots, plan.blocked_libs,
    )
    base_path = [p for p in result.get("PATH", "/usr/bin:/bin").split(":")
                 if p and p not in module_bins]
    result["PATH"] = ":".join(conda_bins + module_bins + ["/usr/local/bin"] + base_path)
    base_ld = [p for p in result.get("LD_LIBRARY_PATH", "").split(":")
               if p and p not in module_libs]
    result["LD_LIBRARY_PATH"] = ":".join(all_lib_dirs + base_ld)
    return result


def render_definition(
    plan: DependencyPlan, env_vars: Mapping[str, str], singularity_image: str,
) -> str:
    """Return definition text for an already resolved plan."""
    project_files = plan.project_files
    blocked_libs = plan.blocked_libs
    copy_roots = plan.copy_roots
    exclude_paths = plan.exclude_paths
    all_files = sorted(set(project_files + blocked_libs))
    files_section = (
        "\n".join(f"    {p}" for p in all_files)
        if all_files else "    # (no project files detected)"
    )

    rsync_lines = []
    for root in copy_roots:
        container_dest = '"${SINGULARITY_ROOTFS}"' + shlex.quote(root)
        rsync_lines.append(f"    mkdir -p {container_dest}")
        exclusions = "".join(
            " --exclude=" + shlex.quote("/" + str(Path(path).relative_to(root)))
            for path in exclude_paths if path != root and _path_is_under(path, root)
        )
        rsync_lines.append(f"    rsync -rL{exclusions} {shlex.quote(root + '/')} {container_dest}/")

    rsync_section = "\n".join(rsync_lines) if rsync_lines else "    # (no module roots detected)"

    env_vars = prepare_environment(plan, env_vars)

    env_section = "\n".join(
        f"    export {k}={_shell_quote(v)}" for k, v in sorted(env_vars.items())
    )

    def_content = DEF_TEMPLATE.format(
        singularity_image=singularity_image,
        files_section=files_section,
        rsync_section=rsync_section,
        env_section=env_section,
    )
    return def_content
