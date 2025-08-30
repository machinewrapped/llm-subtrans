import pysubs2


class SimpleColor:
    """
    Simple color representation for JSON serialization.
    Supports conversion to/from pysubs2.Color and #RRGGBBAA format.
    """

    def __init__(self, r : int, g : int, b : int, a : int = 255):
        self.r = max(0, min(255, r))
        self.g = max(0, min(255, g))
        self.b = max(0, min(255, b))
        self.a = max(0, min(255, a))

    @classmethod
    def from_pysubs2(cls, color : pysubs2.Color) -> 'SimpleColor':
        """Create SimpleColor from pysubs2.Color"""
        return cls(color.r, color.g, color.b, color.a)

    @classmethod
    def from_hex(cls, hex_str : str) -> 'SimpleColor':
        """Create SimpleColor from #RRGGBB or #RRGGBBAA format"""
        hex_str = hex_str.lstrip('#')
        if len(hex_str) == 6:
            hex_str += 'FF'  # Add full alpha if not specified
        elif len(hex_str) != 8:
            raise ValueError(f"Invalid hex color format: #{hex_str}")

        return cls(
            int(hex_str[0:2], 16),
            int(hex_str[2:4], 16),
            int(hex_str[4:6], 16),
            int(hex_str[6:8], 16)
        )

    def to_pysubs2(self) -> pysubs2.Color:
        """Convert to pysubs2.Color"""
        return pysubs2.Color(self.r, self.g, self.b, self.a)

    def to_hex(self) -> str:
        """Convert to #RRGGBBAA format"""
        return f"#{self.r:02X}{self.g:02X}{self.b:02X}{self.a:02X}"

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dict"""
        return {'r': self.r, 'g': self.g, 'b': self.b, 'a': self.a}

    @classmethod
    def from_dict(cls, d : dict) -> 'SimpleColor':
        """Create from dict"""
        return cls(d['r'], d['g'], d['b'], d.get('a', 255))