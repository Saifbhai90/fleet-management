# Sample Excel Formats – Task Report (Admin Uploads)

Admin **daily** do Excel files upload karega. Unke format samajhne ke liye is folder mein **sample workbooks** rakhein.

---

## 1. EmergencyTaskReport

- **File name (suggested):** `EmergencyTaskReport.xlsx` (ya jis naam se upload karenge)
- **Purpose:** Tasks ki details – is se **EMG, Tasks (admin)** column fill hogi.
- **Required:** Har row mein **date**, **vehicle identifier** (Vehicle No ya ID), aur **EMG task count** (ya task details) honi chahiye taake hum report mein date + vehicle ke hisaab se match kar saken.

**Is folder mein sample file rakhein:** `EmergencyTaskReport_sample.xlsx`  
Jab aap file rakh den, batayein – main us format ke mutabiq parser likh dunga.

---

## 2. Vehicle Mileage Report

- **File name (suggested):** `VehicleMileageReport.xlsx` (ya jis naam se upload karenge)
- **Purpose:** Tracker se mile **Tracker Driven KMs** – is se **Tracker Driven KMs (admin)** column fill hogi.
- **Required:** Har row mein **date**, **vehicle identifier** (Vehicle No ya ID), aur **tracker KMs** (decimal number) honi chahiye.

**Is folder mein sample file rakhein:** `VehicleMileage_report_sample.xlsx`  
Jab aap file rakh den, batayein – main us format ke mutabiq parser likh dunga.

---

## Format Guide (aap fill karenge)

Jab sample files is folder mein rakh den:

1. **EmergencyTaskReport_sample.xlsx** – Batayein:
   - Kaunsi sheet use karni hai (first sheet ya koi specific name)?
   - Date ka column kaun sa hai (column letter/name)?
   - Vehicle No ka column kaun sa hai?
   - EMG Tasks count ka column kaun sa hai (ya kaise derive karna hai)?

2. **VehicleMileage_report_sample.xlsx** – Batayein:
   - Kaunsi sheet use karni hai?
   - Date ka column kaun sa hai?
   - Vehicle No ka column kaun sa hai?
   - Tracker KMs ka column kaun sa hai?

Is ke baad code mein Excel parse logic unhi columns ke hisaab se add kar di jayegi.
