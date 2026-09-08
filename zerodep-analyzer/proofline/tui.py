import sys
from .core import run_analysis

try:
    import curses
except ImportError:
    curses = None

def run_tui(before_dir: str, after_dir: str):
    """
    Launch the interactive terminal UI using curses.
    """
    if curses is None:
        print("Error: The native 'curses' standard library module is not available on this platform.")
        print("To use the TUI without dependencies, please run Proofline on a Unix/Linux environment.")
        return False

    print("Analyzing repository for TUI...")
    diff, cg, cr, routes, ta, tw, rr, eg = run_analysis(before_dir, after_dir)

    def draw_menu(stdscr):
        curses.curs_set(0)
        stdscr.nodelay(False)
        
        symbols = list(eg.nodes.keys()) if eg.nodes else ["No changes detected."]
        
        current_row = 0
        
        while True:
            stdscr.clear()
            h, w = stdscr.getmaxyx()
            
            title = f" Proofline TUI - Total Severity: {rr.overall_severity.name} "
            stdscr.addstr(0, max(0, (w - len(title)) // 2), title, curses.A_REVERSE)
            
            for idx, row in enumerate(symbols):
                if idx >= h - 4:
                    break
                x = 2
                y = 2 + idx
                
                if idx == current_row:
                    stdscr.attron(curses.color_pair(1) if curses.has_colors() else curses.A_REVERSE)
                    stdscr.addstr(y, x, f"> {row}")
                    stdscr.attroff(curses.color_pair(1) if curses.has_colors() else curses.A_REVERSE)
                else:
                    stdscr.addstr(y, x, f"  {row}")
            
            stdscr.addstr(h - 1, 2, "Press UP/DOWN to navigate, Q to quit.")
            stdscr.refresh()
            
            key = stdscr.getch()
            
            if key == curses.KEY_UP and current_row > 0:
                current_row -= 1
            elif key == curses.KEY_DOWN and current_row < len(symbols) - 1:
                current_row += 1
            elif key in [ord('q'), ord('Q')]:
                break

    # Initialize curses colors
    def tui_wrapper(stdscr):
        if curses.has_colors():
            curses.start_color()
            curses.init_pair(1, curses.COLOR_BLACK, curses.COLOR_CYAN)
        draw_menu(stdscr)
        
    curses.wrapper(tui_wrapper)
    return True
