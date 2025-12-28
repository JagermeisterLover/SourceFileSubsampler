<img width="598" height="589" alt="image" src="https://github.com/user-attachments/assets/9cd63ae4-34be-429d-90c9-66ef511af9d5" />


Sometimes you want to use source .dat file with rays for LED, but manufacturers like Luxeon provide only one file with a big amount of rays (5 million), which sometimes is too much. And you cannot decrease number of rays directly in LDE, because .dat file is just a list of rays and Zemax will trace each ray one after another, but rays in .dat files not always randomly distributed in angular space. That may result in uneven illumination distribution. 

This program can:
- randomly subsamples .dat ray files and creates subsampled .dat file.
- convert binary ray file .dat to readable ASCII .txt file
- saving subsampled .dat file is supported for Zemax Opticstudio and TracePro
