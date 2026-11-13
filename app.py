#!/usr/bin/env python3
"""Review two-cell clusters and save one annotation CSV per batch."""

from __future__ import annotations

import argparse
import csv
import os
import re
import tempfile
import tkinter as tk
from datetime import datetime, timezone
from itertools import combinations_with_replacement
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageOps, ImageTk


CELL_TYPES = ("CTC", "Neutrophil", "Monocyte", "NK Cell", "T Cell", "B Cell")
DEFAULT_PAIR = ("CTC", "Neutrophil")
FIXED_LABEL = "CTC + CTC"
OTHERS = "Others"
PENDING_PAIR = "Pending pair selection"
ALL_PAIRS = tuple(
    f"{first} + {second}"
    for first, second in combinations_with_replacement((*CELL_TYPES, "Unknown"), 2)
)
TWO_CELLS = "two_cells"
STAGE_ONE = (
    ("No cluster", "no_cluster"),
    ("Exactly 2 cells", TWO_CELLS),
    ("3 or more cells", "three_or_more"),
    ("Uncertain", "uncertain"),
)
SUPPORTED_EXTENSIONS = {".bmp", ".jpeg", ".jpg", ".pgm", ".png", ".ppm",
                        ".tif", ".tiff", ".webp"}
CSV_FIELDS = ("filename", "relative_path", "cluster_size", "classification",
              "cell_combination", "target_combination", "annotated_at", "image_folder")


def natural_key(value: str) -> list[object]:
    return [int(part) if part.isdigit() else part.casefold()
            for part in re.split(r"(\d+)", value)]


def discover_images(input_dir: Path, recursive: bool) -> list[Path]:
    paths = input_dir.rglob("*") if recursive else input_dir.iterdir()
    return sorted(
        (path for path in paths if path.suffix.casefold() in SUPPORTED_EXTENSIONS
         and path.is_file()),
        key=lambda path: natural_key(path.relative_to(input_dir).as_posix()),
    )


def target_combination(first: str, second: str) -> str:
    members = sorted((first, second), key=CELL_TYPES.index)
    target = " + ".join(members)
    if target == FIXED_LABEL:
        raise ValueError("CTC + CTC already has its own button. Choose a different target.")
    return target


def default_output(input_dir: Path, target: str) -> Path:
    slug = target.replace(" + ", "-").replace(" ", "_")
    return input_dir / f"cluster_review_{slug}.csv"


class AnnotationStore:
    def __init__(self, output: Path, input_dir: Path, target: str) -> None:
        self.output = output
        self.input_dir = input_dir
        self.target = target
        self.rows: dict[str, dict[str, str]] = {}
        self.version = self._version()
        if self.version is None:
            return
        with output.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames != list(CSV_FIELDS):
                raise ValueError("Choose a new CSV or an existing ImageSelector-Cluster CSV.")
            for row in reader:
                if None in row or any(row[field] is None for field in CSV_FIELDS):
                    raise ValueError("The selected CSV has an incomplete row.")
                if row["target_combination"] != target or row["image_folder"] != str(input_dir):
                    raise ValueError(
                        "This CSV belongs to another target or image folder. Choose a separate CSV."
                    )
                relative_path = row["relative_path"]
                if not relative_path or relative_path in self.rows:
                    raise ValueError("The selected CSV has an empty or duplicate image path.")
                self.rows[relative_path] = row

    def _version(self) -> tuple[int, int, int, int] | None:
        try:
            stat = self.output.stat()
        except FileNotFoundError:
            return None
        return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns

    def update(self, relative_path: str, size: str = "", label: str = "",
               combination: str = "") -> None:
        rows = self.rows.copy()
        if size:
            rows[relative_path] = {
                "filename": Path(relative_path).name,
                "relative_path": relative_path,
                "cluster_size": size,
                "classification": label,
                "cell_combination": combination or (label if label in {FIXED_LABEL, self.target} else ""),
                "target_combination": self.target,
                "annotated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "image_folder": str(self.input_dir),
            }
        else:
            rows.pop(relative_path, None)

        self.output.parent.mkdir(parents=True, exist_ok=True)
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", newline="", dir=self.output.parent,
                prefix=f".{self.output.name}.", suffix=".tmp", delete=False,
            ) as handle:
                temp_path = Path(handle.name)
                writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
                writer.writeheader()
                writer.writerows(rows[path] for path in sorted(rows, key=natural_key))
                handle.flush()
                os.fsync(handle.fileno())
            if self._version() != self.version:
                raise ValueError("The CSV changed while this window was open. Reopen the batch.")
            os.replace(temp_path, self.output)
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
        self.version = self._version()
        self.rows = rows

    def complete(self, path: str) -> bool:
        row = self.rows.get(path)
        return bool(row and (
            row["cluster_size"] != TWO_CELLS
            or row["classification"] not in {"", PENDING_PAIR}
        ))


class Reviewer(ttk.Frame):
    def __init__(self, root: tk.Tk, images: list[Path], store: AnnotationStore) -> None:
        super().__init__(root, padding=14)
        self.root = root
        self.images = images
        self.paths = [path.relative_to(store.input_dir).as_posix() for path in images]
        self.store = store
        self.index = next((i for i, path in enumerate(self.paths) if not store.complete(path)), 0)
        self.stage = 1
        self.source_image = None
        self.photo = None
        self.resize_task = None
        self.actions = []
        self.other_pairs = [pair for pair in ALL_PAIRS if pair not in {FIXED_LABEL, store.target}]

        self.pack(fill="both", expand=True)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        self.status = ttk.Label(self)
        self.status.grid(row=0, column=0, sticky="w")
        self.filename = ttk.Label(self)
        self.filename.grid(row=1, column=0, sticky="w", pady=(4, 8))
        self.canvas = tk.Canvas(self, background="#202428", highlightthickness=0)
        self.canvas.grid(row=2, column=0, sticky="nsew")
        self.canvas.bind("<Configure>", self.queue_resize)
        self.question = ttk.Label(self)
        self.question.grid(row=3, column=0, sticky="w", pady=(12, 4))
        self.choices = ttk.Frame(self)
        self.choices.grid(row=4, column=0, sticky="ew")
        navigation = ttk.Frame(self)
        navigation.grid(row=5, column=0, sticky="w", pady=(10, 0))
        for caption, callback in (
            ("Previous", lambda: self.move(-1)), ("Next", lambda: self.move(1)),
            ("Back to cluster size", self.back_to_size), ("Clear", self.clear),
        ):
            ttk.Button(navigation, text=caption, command=callback).pack(side="left", padx=(0, 6))
        self.root.bind("<KeyPress>", self.keypress)
        self.show_image()

    @property
    def path(self) -> str:
        return self.paths[self.index]

    def show_image(self) -> None:
        row = self.store.rows.get(self.path, {})
        self.stage = 2 if row.get("cluster_size") == TWO_CELLS else 1
        if (self.stage == 2 and not row.get("cell_combination")
                and row.get("classification") in {OTHERS, PENDING_PAIR}):
            self.stage = 3
        self.filename.configure(text=self.path)
        self.source_image = None
        self.image_error = ""
        try:
            with Image.open(self.images[self.index]) as image:
                image = ImageOps.exif_transpose(image)
                if image.mode in {"I", "F"} or image.mode.startswith("I;16"):
                    grayscale = image.convert("F")
                    low, high = grayscale.getextrema()
                    if high > low:
                        scale = 255 / (high - low)
                        image = grayscale.point(lambda pixel: (pixel - low) * scale).convert("L")
                self.source_image = image.convert("RGB")
        except (OSError, ValueError) as exc:
            self.image_error = f"Could not open image\n{exc}"
        self.refresh()
        self.queue_resize()

    def queue_resize(self, _event=None) -> None:
        if self.resize_task is not None:
            self.after_cancel(self.resize_task)
        self.resize_task = self.after(40, self.draw_image)

    def draw_image(self) -> None:
        self.resize_task = None
        self.canvas.delete("all")
        width, height = self.canvas.winfo_width(), self.canvas.winfo_height()
        if width <= 1 or height <= 1:
            return
        if self.source_image is None:
            self.photo = None
            self.canvas.create_text(width // 2, height // 2, text=self.image_error,
                                    fill="white", width=max(1, width - 24))
            return
        source_width, source_height = self.source_image.size
        scale = min(width / source_width, height / source_height)
        image = self.source_image.resize(
            (max(1, round(source_width * scale)), max(1, round(source_height * scale))),
            Image.Resampling.LANCZOS,
        )
        self.photo = ImageTk.PhotoImage(image, master=self.canvas)
        self.canvas.create_image(width // 2, height // 2, image=self.photo)

    def refresh(self) -> None:
        row = self.store.rows.get(self.path, {})
        size_labels = {size: caption for caption, size in STAGE_ONE}
        current = row.get("classification") or size_labels.get(row.get("cluster_size"), "Unreviewed")
        completed = sum(self.store.complete(path) for path in self.paths)
        self.status.configure(
            text=f"Image {self.index + 1}/{len(self.images)}  |  Reviewed {completed}/{len(self.images)}"
                 f"  |  Target: {self.store.target}  |  Current: {current}"
        )
        for button in self.choices.winfo_children():
            button.destroy()
        if self.stage == 1:
            self.question.configure(text="Step 1 · How many cells form the cluster?")
            self.actions = [(caption, lambda value=size: self.select_size(value))
                            for caption, size in STAGE_ONE]
        elif self.stage == 2:
            self.question.configure(text="Step 2 · What is the two-cell combination?")
            self.actions = [(label, lambda value=label: self.record(TWO_CELLS, value))
                            for label in (FIXED_LABEL, self.store.target)]
            self.actions.append((OTHERS, self.select_other))
        else:
            self.question.configure(text="Step 3 · Select the exact two-cell combination")
            self.actions = []
            if self.source_image is not None:
                self.show_pair_picker(row.get("cell_combination", ""))
        if self.source_image is None:
            self.actions = []
        for index, (caption, callback) in enumerate(self.actions, 1):
            ttk.Button(self.choices, text=f"{index}  {caption}", command=callback).pack(
                side="left", padx=(0, 6)
            )

    def show_pair_picker(self, current_pair: str) -> None:
        controls = ttk.Frame(self.choices)
        controls.pack(side="left", fill="x", expand=True)
        ttk.Label(controls, text="Search").pack(anchor="w")
        search = tk.StringVar()
        entry = ttk.Entry(controls, textvariable=search)
        entry.pack(fill="x", pady=(2, 4))
        results = ttk.Frame(controls)
        results.pack(fill="x")
        pairs = tk.Listbox(results, height=6, exportselection=False)
        scroll = ttk.Scrollbar(results, command=pairs.yview)
        pairs.configure(yscrollcommand=scroll.set)
        pairs.pack(side="left", fill="x", expand=True)
        scroll.pack(side="right", fill="y")

        def confirm(_event=None):
            selected = pairs.curselection()
            if selected:
                self.record(TWO_CELLS, OTHERS, pairs.get(selected[0]))
            return "break"

        save = ttk.Button(self.choices, text="Save and next", command=confirm, state="disabled")
        save.pack(side="left", padx=8)
        ttk.Button(self.choices, text="Back to Step 2", command=self.back_to_pair).pack(side="left")

        def update_button(_event=None):
            save.state(["!disabled"] if pairs.curselection() else ["disabled"])

        def filter_pairs(*_args):
            query = search.get().casefold().replace("+", " ").split()
            pairs.delete(0, "end")
            for pair in self.other_pairs:
                if all(word in pair.casefold() for word in query):
                    pairs.insert("end", pair)
                    if pair == current_pair:
                        pairs.selection_set("end")
                        pairs.see("end")
            update_button()

        pairs.bind("<<ListboxSelect>>", update_button)
        pairs.bind("<Double-Button-1>", confirm)
        pairs.bind("<Return>", confirm)
        entry.bind("<Return>", confirm)
        search_trace = search.trace_add("write", filter_pairs)
        entry.bind("<Destroy>", lambda _event: search.trace_remove("write", search_trace))
        filter_pairs()

    def select_other(self) -> None:
        row = self.store.rows.get(self.path, {})
        if row.get("classification") in {OTHERS, PENDING_PAIR} or self.save(TWO_CELLS, PENDING_PAIR):
            self.stage = 3
            self.refresh()

    def back_to_pair(self) -> None:
        if self.store.rows.get(self.path, {}).get("classification") == PENDING_PAIR:
            if not self.save(TWO_CELLS):
                return
        self.stage = 2
        self.refresh()

    def save(self, size: str = "", label: str = "", combination: str = "") -> bool:
        try:
            self.store.update(self.path, size, label, combination)
        except (OSError, ValueError) as exc:
            messagebox.showerror("Could not save review", str(exc), parent=self.root)
            return False
        return True

    def select_size(self, size: str) -> None:
        if size != TWO_CELLS:
            self.record(size)
        elif self.store.rows.get(self.path, {}).get("cluster_size") == TWO_CELLS or self.save(size):
            self.stage = 2
            self.refresh()

    def record(self, size: str, label: str = "", combination: str = "") -> None:
        if self.save(size, label, combination):
            if self.index < len(self.images) - 1:
                self.move(1)
            else:
                self.refresh()
                messagebox.showinfo("Last image", f"Review saved to\n{self.store.output}",
                                    parent=self.root)

    def clear(self) -> None:
        if self.path in self.store.rows and self.save():
            self.show_image()

    def move(self, offset: int) -> None:
        index = self.index + offset
        if 0 <= index < len(self.images):
            self.index = index
            self.show_image()

    def back_to_size(self) -> None:
        self.stage = 1
        self.refresh()

    def keypress(self, event) -> None:
        if isinstance(event.widget, (ttk.Entry, tk.Listbox)):
            return
        if event.keysym in {"Left", "Right"}:
            self.move(-1 if event.keysym == "Left" else 1)
        elif event.keysym in {"BackSpace", "Delete"}:
            self.clear()
        elif event.keysym in {"q", "Q", "Escape"}:
            self.root.destroy()
        elif event.char in ("1", "2", "3", "4"):
            index = int(event.char) - 1
            if index < len(self.actions):
                self.actions[index][1]()


class Setup(ttk.Frame):
    def __init__(self, root: tk.Tk, args: argparse.Namespace) -> None:
        super().__init__(root, padding=18)
        self.root = root
        self.input_path = tk.StringVar(value=args.input or "")
        self.output_path = tk.StringVar(value=args.output or "")
        self.first = tk.StringVar(value=args.target[0])
        self.second = tk.StringVar(value=args.target[1])
        self.recursive = tk.BooleanVar(value=args.recursive)
        self.default_hint = tk.StringVar()

        self.pack(fill="both", expand=True)
        self.columnconfigure(1, weight=1)
        for row, caption, variable, browse in (
            (0, "Image folder", self.input_path, self.choose_input),
            (1, "Results CSV", self.output_path, self.choose_output),
        ):
            ttk.Label(self, text=caption).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=4)
            ttk.Entry(self, textvariable=variable).grid(row=row, column=1, sticky="ew")
            ttk.Button(self, text="Browse…", command=browse).grid(row=row, column=2, padx=(8, 0))
        ttk.Label(self, textvariable=self.default_hint, wraplength=510).grid(
            row=2, column=1, columnspan=2, sticky="w"
        )
        ttk.Label(self, text="Target combination").grid(row=3, column=0, sticky="w", pady=(12, 0))
        target = ttk.Frame(self)
        target.grid(row=3, column=1, columnspan=2, sticky="w", pady=(12, 0))
        ttk.Combobox(target, values=CELL_TYPES, textvariable=self.first, state="readonly",
                     width=15).pack(side="left")
        ttk.Label(target, text="+", padding=(6, 0)).pack(side="left")
        ttk.Combobox(target, values=CELL_TYPES, textvariable=self.second, state="readonly",
                     width=15).pack(side="left")
        ttk.Checkbutton(self, text="Include subfolders", variable=self.recursive).grid(
            row=4, column=1, sticky="w", pady=8
        )
        ttk.Button(self, text="Start review", command=self.start).grid(
            row=5, column=1, sticky="w", pady=(6, 0)
        )
        for variable in (self.input_path, self.output_path, self.first, self.second):
            variable.trace_add("write", self.update_hint)
        self.update_hint()

    def update_hint(self, *_args) -> None:
        if self.output_path.get().strip():
            self.default_hint.set("")
            return
        try:
            target = target_combination(self.first.get(), self.second.get())
        except ValueError as exc:
            self.default_hint.set(str(exc))
            return
        filename = default_output(Path("."), target).name
        self.default_hint.set(f"Default: {filename} in the image folder")

    def choose_input(self) -> None:
        selected = filedialog.askdirectory(parent=self.root, mustexist=True)
        if selected:
            self.input_path.set(selected)

    def choose_output(self) -> None:
        selected = filedialog.asksaveasfilename(
            parent=self.root, defaultextension=".csv", confirmoverwrite=False,
            filetypes=[("CSV files", "*.csv")],
        )
        if selected:
            self.output_path.set(selected)

    def start(self) -> None:
        try:
            target = target_combination(self.first.get(), self.second.get())
            image_folder = self.input_path.get().strip()
            if not image_folder:
                raise ValueError("Choose an image folder.")
            input_dir = Path(image_folder).expanduser().resolve()
            if not input_dir.is_dir():
                raise ValueError(f"Image folder does not exist: {input_dir}")
            images = discover_images(input_dir, self.recursive.get())
            if not images:
                raise ValueError("No supported images found in this folder.")
            output = self.output_path.get().strip()
            output_path = Path(output).expanduser().resolve() if output else default_output(
                input_dir, target
            ).resolve()
            if output_path.suffix.casefold() != ".csv":
                raise ValueError("Choose a results filename ending in .csv.")
            store = AnnotationStore(output_path, input_dir, target)
        except (OSError, ValueError) as exc:
            messagebox.showerror("Could not start review", str(exc), parent=self.root)
            return

        self.destroy()
        self.root.geometry("1100x760")
        self.root.minsize(720, 460)
        Reviewer(self.root, images, store)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", help="Initial image folder")
    parser.add_argument("--output", help="Initial results CSV path")
    parser.add_argument("--target", nargs=2, choices=CELL_TYPES, default=DEFAULT_PAIR,
                        metavar=("CELL_1", "CELL_2"), help="Initial target combination")
    parser.add_argument("--recursive", action="store_true", help="Include subfolders")
    args = parser.parse_args()

    root = tk.Tk()
    root.title("ImageSelector Cluster")
    root.geometry("740x260")
    root.minsize(620, 240)
    Setup(root, args)
    root.mainloop()


if __name__ == "__main__":
    main()
