import os
import questionary
import click
import getpass
from apollo.utils.run_command import run_command
from apollo.utils.config import load_allowed_users, cache_apollo_path, load_config, ensure_pypirc
from halo import Halo

@click.option("--test", is_flag=True, help="Push the package to TestPyPI.")
@click.option("--prod", is_flag=True, help="Push the package to Prod PyPI.")
@click.option("--skip-sanity-check", is_flag=True, help="Skip the sanity check step before deployment")
@click.option("--verbose", is_flag=True, help="Useful for additon logging in the case of no deploys")
def deploy(test, prod, skip_sanity_check, verbose):
    """
    Package and push the project to PyPI or TestPyPI.
    Use --test to push to TestPyPI, or --prod to push to Prod PyPI.
    """
    spinner = Halo(spinner="dots")

    # Prevent Unauthorized Deployments
    username = getpass.getuser()
    allowed_users = load_allowed_users()

    if username not in allowed_users:
        spinner.fail(f"Unauthorized user: {username}.")
        spinner.info("Only maintainers can deploy this package.")
        exit(1)
        
    # Ensure the .pypirc file exists and has valid credentials
    ensure_pypirc(test)

    # Ensure Apollo Path is Set
    config = load_config()
    cache_apollo_path(config)
    APOLLO_PATH = config["apollo_path"]

    # Confirm Deployment Environment
    env_choice = "testpypi" if test else "pypi"
    verbose = "--verbose" if verbose else ""
    
    if not questionary.confirm(f"Are you sure you want to deploy to {env_choice}?").ask():
        spinner.fail("Deployment aborted.")
        return

    # Prompt for Release Notes
    release_notes = questionary.text("Enter release notes or changelog for this version (leave blank to skip):").ask()
    changelog_path = "CHANGELOG.md"

    if release_notes.strip():
        if not os.path.exists(changelog_path):
            with open(changelog_path, "w") as changelog_file:
                changelog_file.write("# Changelog\n\n")
            spinner.succeed(f"Created {changelog_path}.")
        with open(changelog_path, "a") as changelog_file:
            changelog_file.write(f"\n## {env_choice} Release Notes\n{release_notes.strip()}\n")
        spinner.info("Release notes appended to CHANGELOG.md.")

    # Build the Package
    os.environ["ENV"] = "prod"  # Set environment to prod
    spinner.info("Environment variable 'ENV' set to 'prod'.")

    log_file = os.path.join(APOLLO_PATH, "sanity_check_errors.log")

    try:
        run_command("rm -rf dist/ build/ *.egg-info", APOLLO_PATH, start="Cleaning previous build artifacts...")
        run_command("python3 -m build", APOLLO_PATH, start="Building the package...")
    except Exception as e:
        spinner.fail(f"Build failed: {e}")
        return

    # Sanity Check
    if not skip_sanity_check:
        try:
            run_command("twine check dist/*", APOLLO_PATH, start="Performing sanity check on the build artifacts...")
            spinner.succeed("Sanity check passed. No build issues detected.")
            
            # Remove the log file if the sanity check passes
            if os.path.exists(log_file):
                os.remove(log_file) 
                
        except Exception as e:
            spinner.fail("Sanity check failed. Build contains errors.")
            with open(log_file, "w") as log_file_handle:
                log_file_handle.write(f"Sanity Check Errors:\n{str(e)}\n")
            spinner.info(f"Error details saved to: {log_file}")
            print(f"\nSanity Check Errors:\n{str(e)}")  # Print the log to the terminal
            return

    # Push to PyPI or TestPyPI
    try:
        run_command(f"python3 -m twine upload --repository {env_choice} dist/* {verbose}", APOLLO_PATH, start=f"Pushing package to {env_choice}...")
        spinner.succeed(f"Package successfully pushed to {env_choice}!")
    except Exception as e:
        spinner.fail(f"Deployment failed: {e}")