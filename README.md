<img width="620" height="607" alt="image" src="https://github.com/user-attachments/assets/01844c22-ab5b-4441-b328-9d5825bdb137" />


Sometimes you want to use source .dat file with rays for LED, but manufacturers like Luxeon provide only one file with a big amount of rays (5 million), which sometimes is too much. And you cannot decrease number of rays directly in LDE, because .dat file is just a list of rays and Zemax will trace each ray one after another, but rays in .dat files not always randomly distributed in angular space. That may result in uneven illumination distribution. 

This program has GUI (Qt) and can do following:
- randomly subsample .dat ray files and create subsampled ray file as:
  - .dat binary for Zemax Opticstudio
  - .dat binary for TracePro
  - readable .txt ASCII file
- convert binary ray file .dat to readable ASCII .txt file
