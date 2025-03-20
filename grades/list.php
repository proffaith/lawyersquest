<?php
//include("index.html");
//$nav=2;
// Connect to the MySQL database
$conn = mysqli_connect('localhost','GradesCheck','44C#atlantic','OERAnalysis');

// Check the connection
if (!$conn) {
    die("Connection failed: " . mysqli_connect_error());
}

// Retrieve data from the database
$sql = "select dataID, StudentID, Term, Section, Age, IsMaleT1, isWhiteAsianT1, OverallHoursAttempted, OverallGPA from mngt140data where isWhiteAsianT1 is null AND Term in ('202321', '202351','202391') order by Term, Section, StudentID;";
$result = mysqli_query($conn, $sql);

// Build the HTML table
if (mysqli_num_rows($result) > 0) {

    echo "<table><thead>";
    echo "<tr align='center'>";
    echo "<th valign='center'>StudentID</th>";
    echo "<th valign='center'>Term</th>";
    echo "<th valign='center'>Section</th>";
    echo "<th valign='center'>Age</th>";
    echo "<th valign='center'>Gender</th>";
    echo "<th valign='center'>Race</th>";
    echo "<th valign='center'>Hours Attempted</th>";
    echo "<th valign='center'>GPA</th>";
    echo "</tr></thead>";

    while ($row = mysqli_fetch_assoc($result)) {

        echo "<tr>";
        echo "<td valign='center'>". $row["StudentID"] . "</td>";
        echo "<td valign='center'><a href='https://simon.ccbcmd.edu/pls/PROD/bwlkoids.P_AdvIDSel' target='_blank'>" . $row["Term"] . "</a></td>";
        echo "<td valign='center'>" . $row["Section"] . "</td>";

        // Form for updating data
        echo "<td width='150' valign='center'>";
        echo "<form method='POST' action='index.php'>";
        echo "<input type='hidden' name='dataID' value='" . $row["dataID"] . "'>";
        echo "<input type='hidden' name='nav' value='10'>";
        echo "<input type='text' id='Age' name='Age' value='".$row["Age"]."'>";
        echo "</td>";

        echo "<td>";
        echo "<select name='gender'>";
        echo "<option value= ></option>";
        echo "<option value=1 " . ($row["IsMaleT1"] == '1' ? "selected" : "") . ">Male</option>";
        echo "<option value=0 " . ($row["IsMaleT1"] == '0' ? "selected" : "") . ">Female</option>";
        echo "</select>";
        echo "</td>";

        echo "<td>";
        echo "<select name='race'>";
        echo "<option value= ></option>";
        echo "<option value=1 " . ($row["isWhiteAsianT1"] == '1' ? "selected" : "") . ">White/Asian</option>";
        echo "<option value=0 " . ($row["isWhiteAsianT1"] == '0' ? "selected" : "") . ">Not White/Asian</option>";
        echo "</select>";
        echo "</td>";

        echo "<td>";
        echo "<input type='text' id='credits' name='credits' value='".$row["OverallHoursAttempted"]."'>";
        echo "</td>";

        echo "<td>";
        echo "<input type='text' id='gpa' name='gpa' value='".$row["OverallGPA"]."'>";
        echo "</td>";

        echo "<td valign='center'>";
        echo "<input type='submit' value='Update'>";
        echo "</form>";
        echo "</td>";
        echo "</tr>";


        }

    echo "</table>";
    echo "<p>A total of ". mysqli_num_rows($result)." records were returned.<br>";
} else {
    echo "<p>No data found.";
}



// Close
?>
