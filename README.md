<img width="476" height="503" alt="image" src="https://github.com/user-attachments/assets/b866516b-219f-4241-aca6-54fba9777cb6" />

Sometimes you want to use source DLL file for LED, but manufacturers like Luxeon provide only one file with a lot of rays (5 million), which sometimes is too much. And you cannot decrease number of rays directly in zemax, because it treats .dat file as a list and traces each ray one after another, not randomly. That intrduces uneven illumination distribution. 

This program subsamples .dat ray files and creates subsampled .dat file.
