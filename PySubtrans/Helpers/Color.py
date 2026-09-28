class Color:
    """
    Simple color representation for JSON serialization.
    Supports conversion to/from #RRGGBBAA format.
    """

    def __init__(self, r : int, g : int, b : int, a : int = 0):
        self.r = max(0, min(255, r))
        self.g = max(0, min(255, g))
        self.b = max(0, min(255, b))
        self.a = max(0, min(255, a))

    def __eq__(self, value: object) -> bool:
        if not isinstance(value, Color):
            return False

        return (self.r, self.g, self.b, self.a) == (value.r, value.g, value.b, value.a)

    def __repr__(self) -> str:
        return f"Color(r={self.r}, g={self.g}, b={self.b}, a={self.a})"

    @classmethod
    def from_hex(cls, hex_str : str) -> 'Color':
        """Create Color from #RRGGBB or #RRGGBBAA format"""
        hex_str = hex_str.lstrip('#')
        if len(hex_str) == 6:
            hex_str += '00'  # Add full alpha if not specified, making it opaque
        elif len(hex_str) != 8:
            raise ValueError(f"Invalid hex color format: #{hex_str}")

        return cls(
            int(hex_str[0:2], 16),
            int(hex_str[2:4], 16),
            int(hex_str[4:6], 16),
            int(hex_str[6:8], 16)
        )

    def to_hex(self) -> str:
        """Convert to #RRGGBBAA format"""
        return f"#{self.r:02X}{self.g:02X}{self.b:02X}{self.a:02X}"

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dict"""
        return {'r': self.r, 'g': self.g, 'b': self.b, 'a': self.a}

    @classmethod
    def from_dict(cls, d : dict) -> 'Color':
        """Create from dict"""
        return cls(d['r'], d['g'], d['b'], d.get('a', 0))