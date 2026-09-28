
def VersionNumberLessThan(version1: str, version2: str) -> bool:
    """Compare two version strings and return True if version1 is less than version2"""
    if not version1:
        return True
        
    # Strip 'v' prefix if present
    v1 = version1[1:] if version1.startswith('v') else version1
    v2 = version2[1:] if version2.startswith('v') else version2
    
    # Split into components and convert to integers
    v1_parts = [int(x) for x in v1.split('.')]
    v2_parts = [int(x) for x in v2.split('.')]
    
    # Compare each component
    for i in range(max(len(v1_parts), len(v2_parts))):
        v1_part = v1_parts[i] if i < len(v1_parts) else 0
        v2_part = v2_parts[i] if i < len(v2_parts) else 0
        if v1_part < v2_part:
            return True
        if v1_part > v2_part:
            return False

    return False
