import os
import random
import struct

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
	QApplication,
	QButtonGroup,
	QFileDialog,
	QHBoxLayout,
	QLabel,
	QLineEdit,
	QMainWindow,
	QMessageBox,
	QProgressBar,
	QPushButton,
	QRadioButton,
	QStyleFactory,
	QVBoxLayout,
	QWidget,
	QGroupBox,
	QFrame,
    QComboBox,
)


class DatToTxtWorker(QObject):
	progress_changed = Signal(int)
	status_changed = Signal(str)
	finished = Signal(str)
	error = Signal(str)

	def __init__(self, input_file, output_file):
		super().__init__()
		self.input_file = input_file
		self.output_file = output_file

	def run(self):
		try:
			self.progress_changed.emit(0)
			self.status_changed.emit("Reading binary header...")

			header_fmt = '<ii100sfffffff i 3f3f3f4fiiii'
			header_size = struct.calcsize(header_fmt)

			with open(self.input_file, 'rb') as fin:
				head_data = fin.read(header_size)
				if len(head_data) != header_size:
					raise ValueError("File too small to contain valid header")
				header = struct.unpack(header_fmt, head_data)
				identifier = header[0]
				nbr_rays = header[1]
				description = header[2]
				source_flux = header[3]
				ray_set_flux = header[4]
				wavelength = header[5]
				azimuth_beg = header[6]
				azimuth_end = header[7]
				polar_beg = header[8]
				polar_end = header[9]
				dimension_units = header[10]
				# 11..13 loc, 14..16 rot, 17..19 scale, 20..23 unused
				ray_format_type = header[24]
				flux_type = header[25]

				if not (identifier == 1010 or identifier == 8675309):
					raise ValueError(f"Incorrect file identifier: {identifier}")

				if not ((ray_format_type == 0) or (ray_format_type == 2)):
					raise ValueError(f"Incorrect file format identifier: {ray_format_type}")

				if ray_format_type == 0:
					if not (flux_type == 0 or flux_type == 1):
						raise ValueError(f"Incorrect flux type identifier: {flux_type}")
					ray_fmt = '<7f'  # x y z l m n flux
					ray_floats = 7
				else:
					if flux_type != 0:
						raise ValueError(f"Incorrect flux type identifier: {flux_type}")
					ray_fmt = '<8f'  # x y z l m n flux wavelength
					ray_floats = 8

				self.status_changed.emit("Writing ASCII header...")
				with open(self.output_file, 'w') as fout:
					fout.write(f"{nbr_rays} {dimension_units} {ray_format_type} {flux_type} \n")

					self.status_changed.emit("Converting rays...")
					ray_size = struct.calcsize(ray_fmt)
					for i in range(nbr_rays):
						if i % 10000 == 0:
							self.progress_changed.emit(int((i / max(1, nbr_rays)) * 100))
							# keep UI responsive
						ray_data = fin.read(ray_size)
						if len(ray_data) != ray_size:
							raise ValueError(f"Unexpected EOF at ray {i}")
						vals = struct.unpack(ray_fmt, ray_data)
						if ray_floats == 7:
							fout.write(' '.join([f"{v:.6f}" for v in vals[:6]] + [f"{vals[6]:.6e}"]) + " \n")
						else:
							# 8 values for spectral color; match C order
							fout.write(' '.join([f"{v:.6f}" for v in vals[:6]] + [f"{vals[6]:.6e}", f"{vals[7]:.6f}"]) + " \n")

			self.progress_changed.emit(100)
			self.status_changed.emit("Conversion complete")
			self.finished.emit(self.output_file)
		except Exception as e:
			self.error.emit(str(e))
		finally:
			self.progress_changed.emit(0)
			self.status_changed.emit("")


class SubsampleWorker(QObject):
	progress_changed = Signal(int)
	status_changed = Signal(str)
	finished = Signal(str)
	error = Signal(str)

	def __init__(self, input_file, target_rays, output_file, output_format, method):
		super().__init__()
		self.input_file = input_file
		self.target_rays = target_rays
		self.output_file = output_file
		self.output_format = output_format
		self.method = method  # 'random' or 'angular_stratified'

	def run(self):
		try:
			self.progress_changed.emit(0)
			self.status_changed.emit("Loading file...")
			if self.input_file.lower().endswith('.dat'):
				raise ValueError("Binary .dat not supported for subsampling. Convert to ASCII .txt first.")

			with open(self.input_file, 'r') as f:
				lines = f.readlines()

			header_index = next(i for i, line in enumerate(lines) if len(line.split()) == 4 and line.split()[0].isdigit())
			header = lines[header_index].strip()

			ray_lines = []
			total_lines = max(1, len(lines) - (header_index + 1))
			for i, line in enumerate(lines[header_index + 1:]):
				if i % 10000 == 0:
					self.progress_changed.emit(int((i / total_lines) * 50))
				stripped = line.strip()
				if len(stripped.split()) == 7:
					ray_lines.append(line)

			if len(ray_lines) < self.target_rays:
				raise ValueError(f"File has only {len(ray_lines)} rays")

			self.status_changed.emit("Subsampling...")
			self.progress_changed.emit(50)
			if self.method == 'random':
				sampled_rays = random.sample(ray_lines, self.target_rays)
			else:
				sampled_rays = self._subsample_angular_stratified(ray_lines, self.target_rays)

			self.status_changed.emit("Scaling fluxes...")
			original_ray_count = int(header.split()[0])
			scale_factor = original_ray_count / self.target_rays

			ray_data = []
			import math
			for i, line in enumerate(sampled_rays):
				if i % 10000 == 0:
					self.progress_changed.emit(50 + int((i / max(1, self.target_rays)) * 10))
				fields = line.strip().split()
				ray = [float(f) for f in fields]
				# Scale and sanitize flux to ensure Zemax compatibility
				flux_val = ray[6] * scale_factor
				if (not math.isfinite(flux_val)) or flux_val <= 0.0:
					flux_val = 1e-30
				ray[6] = float(flux_val)
				ray_data.append(ray)

			sum_flux = sum(r[6] for r in ray_data)
			parts = header.split()
			parts[0] = str(self.target_rays)
			new_header = ' '.join(parts) + '\n'

			self.status_changed.emit("Saving file...")
			self.progress_changed.emit(60)

			if self.output_format == 'txt':
				with open(self.output_file, 'w') as f:
					f.write(new_header)
					for ray in ray_data:
						f.write(' '.join([f"{v:.6f}" for v in ray[:6]] + [f"{ray[6]:.6e}"]) + '\n')
			elif self.output_format == 'tracepro':
				# Write TracePro ASCII .dat format
				requested = original_ray_count
				generated = self.target_rays
				with open(self.output_file, 'w') as f:
					f.write(f"!! Source file: {self.input_file}\n")
					f.write(f"# NbrRays Requested: {requested},  NbrRays Generated: {generated}\n")
					# Use generic angular range and identity transforms
					f.write("Angular Range PolarBeg:   0.0000, PolarEnd: 180.0000, AzimuthBeg:   0.0000, AzimuthEnd: 360.0000\n")
					f.write("Rotation AboutX   0.0000, AboutY   0.0000, AboutZ   0.0000\n")
					f.write("Translation X   0.0000, Y   0.0000, Z   0.0000\n")
					f.write("Scale X   1.0000, Y   1.0000, Z   1.0000\n")
					f.write("Conversion Factor From Meters   1.0000\n")
					f.write("X Pos Y Pos Z Pos X Vec Y Vec Z Vec Inc Flux\n")
					for i, ray in enumerate(ray_data):
						if i % 10000 == 0:
							self.progress_changed.emit(60 + int((i / max(1, self.target_rays)) * 40))
						x, y, z, l, m, n, flux_val = ray[:7]
						# Sanitize flux
						import math
						if (not math.isfinite(flux_val)) or flux_val <= 0.0:
							flux_val = 1e-30
						f.write(f"{x:.6E} {y:.6E} {z:.6E} {l:.6E} {m:.6E} {n:.6E} {flux_val:.6E} \n")
			else:
				identifier = 8675309
				nbr_rays = self.target_rays
				description = b'Subsampled LUXEON Z ray file'.ljust(100, b'\0')
				source_flux = sum_flux
				ray_set_flux = sum_flux
				wavelength = 0.0
				azimuth_beg = 0.0
				azimuth_end = 0.0
				polar_beg = 0.0
				polar_end = 0.0
				dim_units = int(parts[1])
				loc_x, loc_y, loc_z = 0.0, 0.0, 0.0
				rot_x, rot_y, rot_z = 0.0, 0.0, 0.0
				scale_x, scale_y, scale_z = 1.0, 1.0, 1.0
				unused1, unused2, unused3, unused4 = 0.0, 0.0, 0.0, 0.0
				ray_format_type = int(parts[2])
				flux_type = int(parts[3])
				reserved1, reserved2 = 0, 0

				header_pack = struct.pack('<ii100sfffffff i 3f3f3f4fiiii',
					identifier, nbr_rays, description,
					source_flux, ray_set_flux, wavelength,
					azimuth_beg, azimuth_end, polar_beg, polar_end,
					dim_units,
					loc_x, loc_y, loc_z,
					rot_x, rot_y, rot_z,
					scale_x, scale_y, scale_z,
					unused1, unused2, unused3, unused4,
					ray_format_type, flux_type,
					reserved1, reserved2)

				with open(self.output_file, 'wb') as f:
					f.write(header_pack)
					for i, ray in enumerate(ray_data):
						if i % 10000 == 0:
							self.progress_changed.emit(60 + int((i / max(1, self.target_rays)) * 40))
						# Ensure per-ray flux is finite and >0 before write
						fv = ray[6]
						if (not math.isfinite(fv)) or fv <= 0.0:
							fv = 1e-30
						f.write(struct.pack('<6ff', ray[0], ray[1], ray[2], ray[3], ray[4], ray[5], fv))

			self.progress_changed.emit(100)
			self.status_changed.emit("Done!")
			self.finished.emit(self.output_file)
		except Exception as e:
			self.error.emit(str(e))
		finally:
			self.progress_changed.emit(0)
			self.status_changed.emit("")

	def _subsample_angular_stratified(self, ray_lines, k_target):
		# Bin by (theta, phi) derived from direction cosines (l, m, n)
		# theta in [0, pi], phi in [-pi, pi)
		# Choose a modest grid that preserves structure without huge overhead
		num_theta_bins = 90
		num_phi_bins = 180
		bins = {}
		flux_in_bin = {}

		# Prepass: assign rays to bins and accumulate flux
		for line in ray_lines:
			parts = line.strip().split()
			if len(parts) != 7:
				continue
			l = float(parts[3]); m = float(parts[4]); n = float(parts[5])
			flux = float(parts[6])
			# Numerical guard: normalize direction if needed
			len_dir = max(1e-12, (l*l + m*m + n*n) ** 0.5)
			l /= len_dir; m /= len_dir; n /= len_dir
			# Clamp n to [-1,1] to avoid NaNs
			if n > 1.0: n = 1.0
			if n < -1.0: n = -1.0
			# theta = arccos(n), phi = atan2(m, l)
			# Use math from Python stdlib without importing anew (already allowed)
			import math
			theta = math.acos(n)
			phi = math.atan2(m, l)
			# Map to bin indices
			ti = min(num_theta_bins - 1, max(0, int((theta / math.pi) * num_theta_bins)))
			phi_norm = (phi + math.pi) / (2 * math.pi)  # 0..1
			pj = min(num_phi_bins - 1, max(0, int(phi_norm * num_phi_bins)))
			key = (ti, pj)
			bins.setdefault(key, []).append(line)
			flux_in_bin[key] = flux_in_bin.get(key, 0.0) + max(0.0, flux)

		if not bins:
			return random.sample(ray_lines, k_target)

		# Allocate samples per bin proportional to flux; fallback to counts if zero flux
		total_flux = sum(flux_in_bin.values())
		if total_flux <= 0:
			# fall back to counts
			counts = {k: len(v) for k, v in bins.items()}
			total_count = sum(counts.values())
			alloc = {k: int(round(k_target * (counts[k] / max(1, total_count)))) for k in bins}
		else:
			alloc = {k: int(round(k_target * (flux_in_bin[k] / total_flux))) for k in bins}

		# Ensure at least 1 in non-empty bins, and adjust to exact k_target
		# First pass: cap by bin size
		alloc = {k: min(len(bins[k]), max(1, v)) for k, v in alloc.items()}
		current_total = sum(alloc.values())
		# If too many, remove from bins with smallest residual until match
		if current_total > k_target:
			# sort bins by (alloc - 1) descending keep >=1, remove where possible
			for k in sorted(alloc.keys(), key=lambda kk: alloc[kk], reverse=True):
				while current_total > k_target and alloc[k] > 1:
					alloc[k] -= 1
					current_total -= 1
					if current_total == k_target:
						break
		# If too few, add where there is remaining capacity
		elif current_total < k_target:
			for k in sorted(alloc.keys(), key=lambda kk: len(bins[kk]) - alloc[kk], reverse=True):
				while current_total < k_target and alloc[k] < len(bins[k]):
					alloc[k] += 1
					current_total += 1
					if current_total == k_target:
						break

		# Sample within bins
		result = []
		for key, lines in bins.items():
			k = alloc.get(key, 0)
			if k <= 0:
				continue
			if k >= len(lines):
				result.extend(lines)
			else:
				result.extend(random.sample(lines, k))

		# Trim or pad if slight rounding overshoot remains
		if len(result) > k_target:
			result = result[:k_target]
		elif len(result) < k_target:
			# pad with random from remaining pool (build set once to avoid O(N^2))
			result_set = set(result)
			remaining = [l for l in ray_lines if l not in result_set]
			need = k_target - len(result)
			if remaining:
				result.extend(random.sample(remaining, min(need, len(remaining))))
		return result


class RaySubsamplerWindow(QMainWindow):
	def __init__(self):
		super().__init__()
		self.setWindowTitle("Zemax Ray Subsampler")
		self.setMinimumSize(480, 360)

		self.input_file = None
		self.header = None
		self.ray_count = None
		self.worker_thread = None
		self.worker = None
		self.convert_thread = None
		self.convert_worker = None

		self._build_ui()

	def _build_ui(self):
		central = QWidget(self)
		self.setCentralWidget(central)

		root_layout = QVBoxLayout(central)
		root_layout.setContentsMargins(16, 16, 16, 16)
		root_layout.setSpacing(12)

		# Steps / instructions
		steps = QGroupBox("Steps")
		steps_layout = QVBoxLayout(steps)
		steps_layout.setSpacing(4)
		steps_labels = [
			"1. Load an ASCII .txt ray file (not .dat)",
			"2. Enter target ray count",
			"3. Choose output format (.txt or .dat)",
			"4. Click Process and Save",
		]
		for text in steps_labels:
			lbl = QLabel(text)
			steps_layout.addWidget(lbl)
		root_layout.addWidget(steps)

		# File row
		file_row = QHBoxLayout()
		self.file_label = QLabel("No file loaded")
		self.file_label.setStyleSheet("color: #666;")
		btn_browse = QPushButton("Load File…")
		btn_browse.clicked.connect(self.on_browse)
		self.btn_convert = QPushButton("Convert .dat → .txt…")
		self.btn_convert.clicked.connect(self.on_convert)
		file_row.addWidget(self.file_label, 1)
		file_row.addWidget(btn_browse, 0)
		file_row.addWidget(self.btn_convert, 0)
		root_layout.addLayout(file_row)

		# Ray count display
		self.ray_count_label = QLabel("Ray count: Unknown")
		root_layout.addWidget(self._divider())
		root_layout.addWidget(self.ray_count_label)

		# Target rays input
		target_row = QHBoxLayout()
		target_row.addWidget(QLabel("Target rays:"))
		self.target_input = QLineEdit()
		self.target_input.setText("100000")
		self.target_input.setPlaceholderText("e.g., 100000")
		self.target_input.setClearButtonEnabled(True)
		target_row.addWidget(self.target_input)
		root_layout.addLayout(target_row)

		# Format selection
		format_row = QHBoxLayout()
		format_row.addWidget(QLabel("Save as:"))
		self.radio_txt = QRadioButton(".txt (ASCII)")
		self.radio_dat = QRadioButton(".dat (Binary)")
		self.radio_tracepro = QRadioButton(".dat (TracePro ASCII)")
		self.radio_txt.setChecked(True)
		group = QButtonGroup(self)
		group.addButton(self.radio_txt)
		group.addButton(self.radio_dat)
		group.addButton(self.radio_tracepro)
		format_row.addWidget(self.radio_txt)
		format_row.addWidget(self.radio_dat)
		format_row.addWidget(self.radio_tracepro)
		format_row.addStretch(1)
		root_layout.addLayout(format_row)

		# Sampling method selection
		method_row = QHBoxLayout()
		method_row.addWidget(QLabel("Sampling method:"))
		self.method_combo = QComboBox()
		self.method_combo.addItem("Random", userData='random')
		self.method_combo.addItem("Angular stratified", userData='angular_stratified')
		method_row.addWidget(self.method_combo)
		method_row.addStretch(1)
		root_layout.addLayout(method_row)

		# Process button
		self.btn_process = QPushButton("Process and Save")
		self.btn_process.clicked.connect(self.on_process)
		root_layout.addWidget(self.btn_process)

		# Progress
		self.progress = QProgressBar()
		self.progress.setRange(0, 100)
		self.status_label = QLabel("")
		root_layout.addWidget(self.progress)
		root_layout.addWidget(self.status_label)

		# Styling
		self.setStyleSheet(
			"""
			QMainWindow { background: #fafafa; }
			QGroupBox { border: 1px solid #e0e0e0; border-radius: 6px; margin-top: 12px; }
			QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; color: #333; }
			QPushButton { padding: 6px 12px; }
			QLineEdit { padding: 6px 8px; }
			QLabel { color: #333; }
			QProgressBar { height: 12px; border: 1px solid #e0e0e0; border-radius: 6px; }
			QProgressBar::chunk { background-color: #2d7ff9; border-radius: 6px; }
			"""
		)

	def _divider(self):
		line = QFrame()
		line.setFrameShape(QFrame.HLine)
		line.setFrameShadow(QFrame.Sunken)
		return line

	def on_browse(self):
		fname, _ = QFileDialog.getOpenFileName(self, "Select Ray File", os.getcwd(), "Text files (*.txt);;DAT files (*.dat)")
		if not fname:
			return
		self.input_file = fname
		self.file_label.setText(os.path.basename(fname))

		if fname.lower().endswith('.dat'):
			QMessageBox.information(self, "Info", "Binary .dat loaded. You can convert it to ASCII .txt using the 'Convert .dat → .txt…' button.")
			self.ray_count_label.setText("Ray count: N/A (Binary file)")
			return

		try:
			with open(fname, 'r') as f:
				lines = f.readlines()
			header_index = next(i for i, line in enumerate(lines) if len(line.split()) == 4 and line.split()[0].isdigit())
			self.header = lines[header_index].strip()
			ray_lines = [line for line in lines[header_index + 1:] if len(line.split()) == 7]
			self.ray_count = len(ray_lines)
			self.ray_count_label.setText(f"Ray count: {self.ray_count}")
		except Exception as e:
			QMessageBox.critical(self, "Error", f"Failed to scan file: {e}")
			self.ray_count = None

	def on_convert(self):
		if not self.input_file or not self.input_file.lower().endswith('.dat'):
			QMessageBox.information(self, "Info", "Load a .dat file first to convert.")
			return

		outfile, _ = QFileDialog.getSaveFileName(self, "Save ASCII .txt", os.getcwd(), "Text files (*.txt)")
		if not outfile:
			return
		if not outfile.lower().endswith('.txt'):
			outfile = f"{outfile}.txt"

		self.btn_convert.setEnabled(False)
		self.btn_process.setEnabled(False)
		self.progress.setValue(0)
		self.status_label.setText("")

		# Use a dedicated thread for conversion to avoid cross-thread reuse
		self.convert_thread = QThread()
		self.convert_worker = DatToTxtWorker(self.input_file, outfile)
		self.convert_worker.moveToThread(self.convert_thread)
		self.convert_thread.started.connect(self.convert_worker.run)
		self.convert_worker.progress_changed.connect(self.progress.setValue)
		self.convert_worker.status_changed.connect(self.status_label.setText)
		self.convert_worker.finished.connect(self._after_convert_success)
		self.convert_worker.error.connect(self.on_error)
		# Clean shutdown and cleanup
		self.convert_worker.finished.connect(self.convert_thread.quit)
		self.convert_worker.error.connect(self.convert_thread.quit)
		self.convert_thread.finished.connect(self.convert_worker.deleteLater)
		self.convert_thread.finished.connect(self.convert_thread.deleteLater)
		self.convert_thread.finished.connect(lambda: (self.btn_convert.setEnabled(True), self.btn_process.setEnabled(True)))
		self.convert_thread.start()

	def _after_convert_success(self, path):
		QMessageBox.information(self, "Converted", f".dat converted to ASCII:\n{path}\n\nIt is now loaded for subsampling.")
		# Load the new txt as input and rescan
		self.input_file = path
		self.file_label.setText(os.path.basename(path))
		try:
			with open(path, 'r') as f:
				lines = f.readlines()
			header_index = next(i for i, line in enumerate(lines) if len(line.split()) == 4 and line.split()[0].isdigit())
			self.header = lines[header_index].strip()
			ray_lines = [line for line in lines[header_index + 1:] if len(line.split()) == 7]
			self.ray_count = len(ray_lines)
			self.ray_count_label.setText(f"Ray count: {self.ray_count}")
		except Exception as e:
			QMessageBox.warning(self, "Warning", f"Loaded converted file, but scan failed: {e}")

	def on_process(self):
		if not self.input_file or not os.path.exists(self.input_file):
			QMessageBox.critical(self, "Error", "No file loaded or file does not exist!")
			return

		try:
			target_rays = int(self.target_input.text().strip())
		except ValueError:
			QMessageBox.critical(self, "Error", "Invalid target rays")
			return

		if self.radio_txt.isChecked():
			output_format = 'txt'
			filters = "TXT files (*.txt)"
			default_ext = '.txt'
		elif self.radio_dat.isChecked():
			output_format = 'dat'
			filters = "DAT files (*.dat)"
			default_ext = '.dat'
		else:
			output_format = 'tracepro'
			filters = "DAT files (*.dat)"
			default_ext = '.dat'
		caption = "Save Output"
		outfile, _ = QFileDialog.getSaveFileName(self, caption, os.getcwd(), filters)
		if not outfile:
			return

		# Ensure correct extension
		if not outfile.lower().endswith(default_ext):
			outfile = f"{outfile}{default_ext}"

		self.btn_process.setEnabled(False)
		self.status_label.setText("")
		self.progress.setValue(0)

		self.worker_thread = QThread()
		method_code = self.method_combo.currentData()
		self.worker = SubsampleWorker(self.input_file, target_rays, outfile, output_format, method_code)
		self.worker.moveToThread(self.worker_thread)
		self.worker_thread.started.connect(self.worker.run)
		self.worker.progress_changed.connect(self.progress.setValue)
		self.worker.status_changed.connect(self.status_label.setText)
		self.worker.finished.connect(self.on_finished)
		self.worker.error.connect(self.on_error)
		self.worker.finished.connect(self.worker_thread.quit)
		self.worker.error.connect(self.worker_thread.quit)
		self.worker_thread.finished.connect(lambda: self.btn_process.setEnabled(True))
		self.worker_thread.start()

	def on_finished(self, path):
		QMessageBox.information(self, "Success", f"File saved as:\n{path}")

	def on_error(self, msg):
		QMessageBox.critical(self, "Error", msg)


def main():
	app = QApplication.instance() or QApplication([])
	QApplication.setStyle(QStyleFactory.create("Fusion"))
	win = RaySubsamplerWindow()
	win.show()
	app.exec()


if __name__ == "__main__":
	main()