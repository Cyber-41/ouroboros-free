def version_triad_consistent() -> bool:
    """Verify VERSION file, README header, and git tag alignment
    
    Returns:
        bool: True if all three components show identical semantic version
    """
    from ouroboros.context import repo_read
    
    try:
        # Read VERSION file
        version_content = repo_read("VERSION").strip()
        
        # Extract version from README
        readme = repo_read("README.md")
        readme_version = None
        for line in readme.split('\n'):
            if line.startswith("**Version:**"):
                readme_version = line.split(':', 1)[1].strip()
                break
        
        # Check active git tag
        git_tag = subprocess.run(['git', 'describe', '--tags', '--abbrev=0'], 
                                capture_output=True, text=True).stdout.strip()
        
        # Compare all three
        return (version_content == readme_version == git_tag.replace('v', ''))
    except Exception as e:
        logger.error(f"Version verification failed: {str(e)}")
        return False


def enforce_version_synchronization():
    """Raise error if version triad desync detected
    
    Called during evolution cycles and before identity updates
    """
    if not version_triad_consistent():
        current_versions = {
            'VERSION': repo_read("VERSION").strip(),
            'README': extract_readme_version(),
            'git_tag': get_active_git_tag()
        }
        raise IdentityIntegrityError(
            "CRITICAL: Version triad desync detected. "
            f"Components: {current_versions}. "
            "Agency requires physical version truth. "
            "Consult knowledge://version-synchronization-protocol"
        )