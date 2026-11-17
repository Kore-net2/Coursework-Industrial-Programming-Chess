"""Tkinter desktop interface; expensive operations run away from the UI thread.

"""
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk, font as tkfont

from .analysis import METRICS, overview, players, popular_openings, similar_players, top_players
from .chart import opening_figure
from .storage import AppError, Cancelled, TIME_CONTROLS, open_database, preprocess


class ChessApp(tk.Tk):
    def __init__(self):
        from .runtime import configure_tk
        configure_tk()
        super().__init__()
        self.title("Chess Analytics | F20SC")
        self.geometry("1120x800")
        self.minsize(920, 680)
        self.database = None
        self.player_names = []
        self.events = queue.Queue()
        self.cancel = threading.Event()
        self.busy = False
        self.closing = False
        self.actions = []
        self.chart_canvas = None
        self.chart_toolbar = None
        self.last_figure = None
        self.status = tk.StringVar(value="Start by importing PGN data or opening a prepared database.")
        self.file_label = tk.StringVar(value="No dataset loaded")
        self.stats_label = tk.StringVar(value="Import a .pgn.zst file to explore players and openings.")
        self.style_ui()
        self.build_ui()
        self.protocol("WM_DELETE_WINDOW", self.close_app)
        self.after(100, self.poll)

    def style_ui(self):
        style = ttk.Style(self)
        for theme in ("vista", "xpnative", "winnative"):
            if theme in style.theme_names():
                style.theme_use(theme)
                break
        self.ui_font = tkfont.nametofont("TkDefaultFont")
        self.title_font = self.ui_font.copy()
        self.title_font.configure(size=abs(self.ui_font.cget("size")) * 2, weight="bold")
        self.section_font = self.ui_font.copy()
        self.section_font.configure(size=abs(self.ui_font.cget("size")) + 3, weight="bold")
        self.heading_font = self.ui_font.copy()
        self.heading_font.configure(weight="bold")
        self.option_add("*Font", self.ui_font)
        background = style.lookup("TFrame", "background") or self.cget("background")
        self.configure(background=background)
        style.configure(".", font=self.ui_font)
        style.configure("Title.TLabel", font=self.title_font)
        style.configure("Subtitle.TLabel", font=self.ui_font)
        style.configure("TButton", padding=(12, 7))
        style.configure("Treeview", font=self.ui_font, rowheight=self.ui_font.metrics("linespace") + 12)
        style.configure("Treeview.Heading", font=self.heading_font, padding=7)
        style.configure("TNotebook.Tab", font=self.ui_font, padding=(18, 10))

    def chart_color(self, name, fallback):
        try:
            return "#" + "".join(f"{component // 257:02x}" for component in self.winfo_rgb(name))
        except tk.TclError:
            return fallback

    def action(self, parent, text, command, accent=False):
        button = ttk.Button(parent, text=text, command=lambda: self.guard(command),
                            style="Accent.TButton" if accent else "TButton")
        self.actions.append(button)
        return button

    def guard(self, callback):
        try:
            callback()
        except Exception as exc:
            messagebox.showerror("Unable to complete task", str(exc), parent=self)

    def build_ui(self):
        body = ttk.Frame(self, padding=24)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="Chess Analytics", style="Title.TLabel").pack(anchor="w")
        ttk.Label(body, text="Explore openings. Track improvement. Discover similar players.", style="Subtitle.TLabel").pack(anchor="w", pady=(2, 18))
        dataset = ttk.Frame(body)
        dataset.pack(fill="x", pady=(0, 12))
        self.action(dataset, "Open database", self.load_dialog, True).pack(side="right")
        ttk.Label(dataset, textvariable=self.file_label, font=self.heading_font).pack(anchor="w")
        ttk.Label(dataset, textvariable=self.stats_label, style="Subtitle.TLabel").pack(anchor="w", pady=(4, 0))
        self.notebook = ttk.Notebook(body)
        self.notebook.pack(fill="both", expand=True)
        self.import_tab = ttk.Frame(self.notebook, padding=20)
        self.openings_tab = ttk.Frame(self.notebook, padding=16)
        self.top_tab = ttk.Frame(self.notebook, padding=16)
        self.similar_tab = ttk.Frame(self.notebook, padding=16)
        for tab, title in ((self.import_tab, "1  Import data"), (self.openings_tab, "2  Openings"), (self.top_tab, "3  Improvement"), (self.similar_tab, "4  Similar players")):
            self.notebook.add(tab, text=title)
        self.build_import()
        self.build_openings()
        self.build_top()
        self.build_similar()
        footer = ttk.Frame(body)
        footer.pack(fill="x", pady=(12, 0))
        self.progress = ttk.Progressbar(footer, mode="indeterminate", length=120)
        self.progress.pack(side="right", padx=10)
        self.cancel_button = ttk.Button(footer, text="Cancel task", command=self.cancel.set, state="disabled")
        self.cancel_button.pack(side="right")
        ttk.Label(footer, textvariable=self.status, wraplength=700, style="Subtitle.TLabel").pack(side="left", fill="x", expand=True)

    def build_import(self):
        ttk.Label(self.import_tab, text="Prepare your dataset", font=self.section_font).pack(anchor="w")
        ttk.Label(self.import_tab, text="Read a Lichess .pgn.zst archive or a plain .pgn file. Only bullet, blitz and rapid games are retained.", wraplength=850).pack(anchor="w", pady=(6, 20))
        self.raw_path = tk.StringVar()
        self.output_path = tk.StringVar()
        for label, variable, browse in (("Raw PGN file", self.raw_path, self.browse_raw), ("Output database", self.output_path, self.browse_output)):
            ttk.Label(self.import_tab, text=label).pack(anchor="w", pady=(8, 4))
            row = ttk.Frame(self.import_tab)
            row.pack(fill="x")
            ttk.Entry(row, textvariable=variable).pack(side="left", fill="x", expand=True, padx=(0, 10))
            self.action(row, "Browse…", browse).pack(side="right")
        self.action(self.import_tab, "Import and open dataset", self.import_data, True).pack(anchor="w", pady=20)
        self.import_log = tk.Text(self.import_tab, height=9, wrap="word", relief="sunken", borderwidth=1, padx=14, pady=14, font=self.ui_font, state="disabled")
        self.import_log.pack(fill="both", expand=True)
        self.log("Import details appear here.\n\nMissing or invalid metadata is counted and reported.\nExisting output files are replaced only after a successful import.")

    def build_openings(self):
        row = ttk.Frame(self.openings_tab)
        row.pack(fill="x", pady=(0, 10))
        self.opening_tc = tk.StringVar(value="All")
        self.min_rating, self.max_rating = tk.StringVar(), tk.StringVar()
        ttk.Label(row, text="Time control").pack(side="left", padx=(0, 6))
        ttk.Combobox(row, textvariable=self.opening_tc, values=("All",) + TIME_CONTROLS, state="readonly", width=9).pack(side="left")
        for label, value in (("Min rating", self.min_rating), ("Max rating", self.max_rating)):
            ttk.Label(row, text=label).pack(side="left", padx=(14, 6))
            ttk.Entry(row, textvariable=value, width=8).pack(side="left")
        self.action(row, "Show chart", self.run_openings, True).pack(side="left", padx=14)
        self.action(row, "Save PNG", self.save_chart).pack(side="right")
        ttk.Label(self.openings_tab, text="Leave rating limits blank for an unbounded range. Both bounds are inclusive.", style="Subtitle.TLabel").pack(anchor="w")
        self.chart_frame = ttk.Frame(self.openings_tab)
        self.chart_frame.pack(fill="both", expand=True, pady=(12, 0))
        self.chart_hint = ttk.Label(self.chart_frame, text="Open a dataset, select filters and click Show chart.", anchor="center")
        self.chart_hint.pack(fill="both", expand=True)

    def table(self, parent, columns):
        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=True, pady=(14, 0))
        table = ttk.Treeview(frame, columns=columns, show="headings", selectmode="browse")
        vertical = ttk.Scrollbar(frame, orient="vertical", command=table.yview)
        horizontal = ttk.Scrollbar(frame, orient="horizontal", command=table.xview)
        table.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        table.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        for column in columns:
            table.heading(column, text=column)
            table.column(column, width=420 if column == "Profile" else 155, minwidth=100, anchor="w")
        return table

    def build_top(self):
        row = ttk.Frame(self.top_tab)
        row.pack(fill="x")
        self.top_tc = tk.StringVar(value="blitz")
        ttk.Label(row, text="Time control").pack(side="left", padx=(0, 8))
        ttk.Combobox(row, textvariable=self.top_tc, values=TIME_CONTROLS, state="readonly", width=12).pack(side="left")
        self.action(row, "Find top 10", self.run_top, True).pack(side="left", padx=12)
        ttk.Label(self.top_tab, text="Change = final post-game rating − first pre-game rating, ordered by game timestamp.", style="Subtitle.TLabel").pack(anchor="w", pady=(12, 0))
        self.top_table = self.table(self.top_tab, ("Player", "Initial", "Final", "Change", "Games"))

    def build_similar(self):
        row = ttk.Frame(self.similar_tab)
        row.pack(fill="x")
        self.search = tk.StringVar()
        self.selected_player = tk.StringVar()
        ttk.Label(row, text="Find player").pack(side="left", padx=(0, 8))
        ttk.Entry(row, textvariable=self.search, width=18).pack(side="left")
        self.player_combo = ttk.Combobox(row, textvariable=self.selected_player, state="readonly", width=25)
        self.player_combo.pack(side="left", padx=8)
        self.search.trace_add("write", lambda *_: self.filter_players())
        self.metric_choice = tk.StringVar(value="Time formats")
        ttk.Combobox(row, textvariable=self.metric_choice, values=("Time formats", "Black openings"), state="readonly", width=16).pack(side="left")
        self.action(row, "Find similar", self.run_similar, True).pack(side="left", padx=8)
        self.target_label = tk.StringVar(value="Choose a player from the dataset. Smaller distance means greater similarity.")
        ttk.Label(self.similar_tab, textvariable=self.target_label, wraplength=940, style="Subtitle.TLabel").pack(anchor="w", pady=(14, 0))
        self.similar_table = self.table(self.similar_tab, ("Player", "Distance", "Profile"))

    def log(self, text):
        self.import_log.configure(state="normal")
        self.import_log.delete("1.0", "end")
        self.import_log.insert("end", text)
        self.import_log.configure(state="disabled")

    def browse_raw(self):
        name = filedialog.askopenfilename(parent=self, title="Choose Lichess PGN", filetypes=[("PGN data", "*.pgn *.zst"), ("All files", "*.*")])
        if name:
            self.raw_path.set(name)
            self.output_path.set(str(Path(name).with_suffix(".sqlite")))

    def browse_output(self):
        name = filedialog.asksaveasfilename(parent=self, title="Save prepared database", defaultextension=".sqlite", filetypes=[("SQLite database", "*.sqlite")])
        if name:
            self.output_path.set(name)

    def load_dialog(self):
        name = filedialog.askopenfilename(parent=self, title="Open prepared database", filetypes=[("SQLite database", "*.sqlite *.db"), ("All files", "*.*")])
        if name:
            self.load_path(name)

    def load_path(self, name):
        def work():
            with open_database(name) as connection:
                connection.set_progress_handler(lambda: int(self.cancel.is_set()), 10000)
                return overview(connection), players(connection)
        def done(result):
            stats, self.player_names = result
            self.database = name
            self.file_label.set(Path(name).name)
            self.stats_label.set(f"{stats['games']:,} games  ·  {len(self.player_names):,} players  ·  {stats['openings']:,} openings  ·  UTC {stats['first'][:10]} to {stats['last'][:10]}" if stats['games'] else "Empty dataset")
            self.search.set("")
            self.filter_players()
            self.fill_table(self.top_table, [])
            self.fill_table(self.similar_table, [])
            self.clear_chart()
            self.target_label.set("Choose a player from the dataset. Distance is measured in percentage points.")
            self.status.set("Dataset ready. Choose an analysis tab.")
        self.start_task("Opening database…", work, done)

    def filter_players(self):
        query = self.search.get().casefold()
        matches = [p for p in self.player_names if query in p.casefold()][:300]
        self.player_combo.configure(values=matches)
        if self.selected_player.get() not in matches:
            self.selected_player.set(matches[0] if matches else "")

    def import_data(self):
        source, target = self.raw_path.get().strip(), self.output_path.get().strip()
        if not source or not target:
            raise AppError("Select both a raw file and an output database.")
        if Path(target).exists() and not messagebox.askyesno("Replace database?", f"Replace {target} after a successful import?", parent=self):
            return
        def done(summary):
            self.log(summary.describe())
            self.load_path(target)
        self.start_task("Importing PGN data…", lambda: preprocess(source, target, lambda msg: self.events.put(("progress", msg)), self.cancel), done)

    def query(self, text, operation, done):
        if not self.database:
            raise AppError("Import a dataset or click Open database first.")
        path = self.database
        def work():
            with open_database(path) as connection:
                connection.set_progress_handler(lambda: int(self.cancel.is_set()), 10000)
                return operation(connection)
        self.start_task(text, work, done)

    def run_openings(self):
        try:
            lower = int(self.min_rating.get()) if self.min_rating.get().strip() else None
            upper = int(self.max_rating.get()) if self.max_rating.get().strip() else None
        except ValueError:
            raise AppError("Rating limits must be whole numbers, or left blank.")
        control = None if self.opening_tc.get() == "All" else self.opening_tc.get()
        subtitle = f"{control or 'All time controls'} | rating {lower if lower is not None else '−∞'} to {upper if upper is not None else '∞'}"
        self.query("Calculating opening popularity…", lambda con: popular_openings(con, control, lower, upper), lambda result: self.show_chart(*result, subtitle))

    def clear_chart(self):
        if self.chart_toolbar:
            self.chart_toolbar.destroy()
            self.chart_toolbar = None
        if self.chart_canvas:
            self.chart_canvas.get_tk_widget().destroy()
            self.chart_canvas = None
        self.last_figure = None
        self.chart_hint.pack(fill="both", expand=True)

    def show_chart(self, total, rows, subtitle):
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
        self.clear_chart()
        self.chart_hint.pack_forget()
        self.last_figure = opening_figure(
            total, rows, subtitle, font_family=self.ui_font.actual("family"),
            colors={"background": self.chart_color("SystemWindow", "white"),
                    "text": self.chart_color("SystemWindowText", "black"),
                    "accent": self.chart_color("SystemHighlight", "#0078d7")})
        self.chart_canvas = FigureCanvasTkAgg(self.last_figure, master=self.chart_frame)
        self.chart_toolbar = NavigationToolbar2Tk(self.chart_canvas, self.chart_frame, pack_toolbar=False)
        self.chart_toolbar.pack(side="bottom", fill="x")
        self.chart_canvas.get_tk_widget().pack(fill="both", expand=True)
        self.chart_canvas.draw()
        self.status.set(f"{total:,} matching games; {len(rows)} openings reach the 1% threshold.")

    def save_chart(self):
        if self.last_figure is None:
            raise AppError("Generate a chart first.")
        path = filedialog.asksaveasfilename(parent=self, defaultextension=".png", filetypes=[("PNG chart", "*.png")])
        if path:
            self.last_figure.savefig(path, dpi=180, bbox_inches="tight")
            self.status.set(f"Chart saved: {Path(path).name}")

    def run_top(self):
        control = self.top_tc.get()
        self.query("Finding most improved players…", lambda con: top_players(con, control), lambda rows: self.fill_table(self.top_table, rows))

    def run_similar(self):
        name = self.selected_player.get()
        if not name or name not in self.player_names:
            raise AppError("Select an existing player from the list. Type part of a name to filter it.")
        key = "time-formats" if self.metric_choice.get() == "Time formats" else "black-openings"
        def done(result):
            target, rows = result
            self.target_label.set(f"{name} — {target}. Distance in percentage points; smaller is more similar.")
            self.fill_table(self.similar_table, rows)
        self.query("Comparing players…", lambda con: similar_players(con, name, METRICS[key]), done)

    def fill_table(self, table, rows):
        table.delete(*table.get_children())
        for row in rows:
            table.insert("", "end", values=[f"{value:.4f}" if isinstance(value, float) else value for value in row.values()])
        self.status.set(f"{len(rows)} players found." if rows else "No matching players in this dataset.")

    def start_task(self, label, work, done):
        if self.busy:
            return
        self.busy = True
        self.cancel.clear()
        self.status.set(label)
        for button in self.actions:
            button.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        self.progress.start(12)
        self.done_callback = done
        def worker():
            try:
                self.events.put(("done", work()))
            except Exception as exc:
                self.events.put(("error", exc))
        threading.Thread(target=worker, daemon=True).start()

    def poll(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "progress":
                    self.status.set(value.split("\n")[0])
                    self.log(value)
                    continue
                self.busy = False
                self.progress.stop()
                self.cancel_button.configure(state="disabled")
                for button in self.actions:
                    button.configure(state="normal")
                if self.closing:
                    self.destroy()
                    return
                if kind == "error":
                    if isinstance(value, Cancelled) or self.cancel.is_set():
                        self.status.set("Task cancelled.")
                    else:
                        self.status.set("Task failed. Correct the input and try again.")
                        messagebox.showerror("Unable to complete task", str(value), parent=self)
                else:
                    self.status.set("Task complete.")
                    self.guard(lambda: self.done_callback(value))
        except queue.Empty:
            pass
        self.after(100, self.poll)

    def close_app(self):
        if self.busy:
            if messagebox.askyesno("Task in progress", "Cancel the current task and close when cleanup finishes?", parent=self):
                self.closing = True
                self.cancel.set()
                self.status.set("Cancelling and cleaning up…")
        else:
            self.destroy()


def launch():
    app = ChessApp()
    app.mainloop()
