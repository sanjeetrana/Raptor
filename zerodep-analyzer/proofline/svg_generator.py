from .evidence_graph import EvidenceGraph
import html

def generate_svg_heatmap(eg: EvidenceGraph) -> str:
    """
    Generate a pure Python SVG blast radius heatmap.
    """
    if not eg.change_summaries:
        return "<svg width='100' height='20'></svg>"

    box_size = 120
    padding = 20
    cols = max(3, min(6, len(eg.change_summaries)))
    rows = (len(eg.change_summaries) + cols - 1) // cols

    width = cols * (box_size + padding) + padding
    height = rows * (box_size + padding) + padding

    colors = {
        "HIGH": "#dc3545",
        "MEDIUM": "#ffc107",
        "LOW": "#0d6efd",
        "INFO": "#6c757d"
    }

    svg = [f'<svg width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg" style="background:#1e1e1e; border-radius:8px; padding:10px;">']
    
    # Add title
    svg.append(f'<text x="{padding}" y="{padding + 10}" fill="#fff" font-family="sans-serif" font-size="16" font-weight="bold">Blast Radius Heatmap</text>')
    
    y_offset = padding + 30
    
    for i, summary in enumerate(eg.change_summaries):
        col = i % cols
        row = i // cols
        
        x = padding + col * (box_size + padding)
        y = y_offset + row * (box_size + padding)
        
        color = colors.get(summary.severity.upper(), "#6c757d")
        
        # Calculate impact size (callers + routes)
        impact = summary.total_callers + len(summary.routes)
        impact_text = f"{impact} affected"
        
        name = summary.symbol_name.split(".")[-1]
        
        svg.append(f'<rect x="{x}" y="{y}" width="{box_size}" height="{box_size}" rx="8" fill="{color}" fill-opacity="0.2" stroke="{color}" stroke-width="2"/>')
        
        # Add symbol name
        escaped_name = html.escape(name)
        if len(escaped_name) > 12:
            escaped_name = escaped_name[:10] + ".."
            
        svg.append(f'<text x="{x+10}" y="{y+40}" fill="#fff" font-family="sans-serif" font-size="14" font-weight="bold">{escaped_name}</text>')
        
        # Add severity
        svg.append(f'<text x="{x+10}" y="{y+70}" fill="{color}" font-family="sans-serif" font-size="12" font-weight="bold">{summary.severity}</text>')
        
        # Add impact
        svg.append(f'<text x="{x+10}" y="{y+100}" fill="#adb5bd" font-family="sans-serif" font-size="11">{impact_text}</text>')

    svg.append("</svg>")
    return "\n".join(svg)


def generate_history_chart(repo_root: str) -> str:
    """Generate an SVG line chart of severity over time."""
    from .history import get_history
    records = get_history(repo_root, limit=20)
    if not records:
        return "<p>No history available.</p>"
        
    width = 600
    height = 200
    padding = 40
    
    # We will plot total_symbols_changed as a line
    max_val = max(r['total_symbols_changed'] for r in records) if records else 1
    max_val = max(max_val, 1)
    
    # X step
    step_x = (width - 2 * padding) / max(1, len(records) - 1)
    
    points = []
    for i, r in enumerate(records):
        x = padding + i * step_x
        y = height - padding - (r['total_symbols_changed'] / max_val) * (height - 2 * padding)
        points.append(f"{x},{y}")
        
    points_str = " ".join(points)
    
    svg = f"""
    <svg width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg" style="background:#1e1e1e; border-radius:8px;">
        <!-- Axes -->
        <line x1="{padding}" y1="{height-padding}" x2="{width-padding}" y2="{height-padding}" stroke="#555" stroke-width="2"/>
        <line x1="{padding}" y1="{padding}" x2="{padding}" y2="{height-padding}" stroke="#555" stroke-width="2"/>
        
        <!-- Data Line -->
        <polyline points="{points_str}" fill="none" stroke="#00ff00" stroke-width="3"/>
        
        <!-- Data Points -->
    """
    for pt, r in zip(points, records):
        cx, cy = pt.split(',')
        color = "#ff4444" if r['overall_severity'] in ("HIGH", "CRITICAL") else "#00ccff"
        svg += f'<circle cx="{cx}" cy="{cy}" r="4" fill="{color}"><title>{r["commit_hash"][:7]} - {r["overall_severity"]}</title></circle>\n'
        
    svg += "</svg>"
    return svg
