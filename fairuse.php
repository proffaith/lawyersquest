<?php
//include("index.html");
//$nav=2;
// Connect to the MySQL database
$conn = mysqli_connect('localhost','MSBABlog','44C#atlantic','MSBABlog');

// Check the connection
if (!$conn) {
    die("Connection failed: " . mysqli_connect_error());
}

// Retrieve data from the database
$sql = "SELECT id, citation, snippet, reviewed, filed_date, parties, date_added, URL, cite_count, subject_matter, who_prevailed, fair_user FROM tbGoogleData where reviewed=0 or reviewed is null order by parties;";
$result = mysqli_query($conn, $sql);

$sql="select id, subject_matter from tbSubjLookup order by subject_matter;";
$sj = mysqli_query($conn, $sql);

// Build the HTML table
if (mysqli_num_rows($result) > 0) {
    echo "<table>";
    echo "<tr align='center'>";
    echo "<td valign='center'>Case</td>";
    echo "<td valign='center'>Cite</td>";
    echo "<td valign='center'>Snippet</td>";
    echo "<td valign='center'>Reviewed</td>";
    echo "<td valign='center'>Fair User</td>";
    echo "<td valign='center'>Who Prevailed</td>";
    echo "<td valign='center'>Subject Matter</td>";

    echo "</tr>";

    while ($row = mysqli_fetch_assoc($result)) {
        echo "<tr>";
        echo "<td valign='top'><a href='" . $row["URL"] . "' target='_blank'>" . $row["parties"] . "</a></td>";
        echo "<td valign='top'>" . $row["citation"] . "</td>";
        echo "<td valign='top'>" . $row["snippet"] . "</td>";

        // Form for updating data
        echo "<td width='100' valign='top'>";
        echo "<form method='POST' action='index.php'>";
        echo "<input type='hidden' name='nav' value='50'>";
        echo "<input type='hidden' name='record_id' value='" . $row["id"] . "'>";
        echo "<select name='reviewed'>";
        echo "<option value=9 " . ($row["reviewed"] == '9' ? "selected" : "") . ">Exclude</option>";
        echo "<option value=1 " . ($row["reviewed"] == '1' ? "selected" : "") . ">Reviewed</option>";
        echo "<option value=0 " . ($row["reviewed"] == '0' ? "selected" : "") . ">Unreviewed</option>";
        echo "</select>";
        echo "</td>";

        echo "<td valign='top'>";
        echo "<select name='fair_user'>";
        echo "<option value=P " . ($row["fair_user"] == 'P' ? "selected" : "") . ">Plaintiff</option>";
        echo "<option value=D " . ($row["fair_user"] == 'D' ? "selected" : "") . ">Defendant</option>";
        echo "</select>";
        echo "</td>";

        echo "<td width='100' valign='top'>";
        echo "<select name='who_prevailed'>";
        echo "<option value=P " . ($row["who_prevailed"] == 'P' ? "selected" : "") . ">Plaintiff</option>";
        echo "<option value=D " . ($row["who_prevailed"] == 'D' ? "selected" : "") . ">Defendant</option>";
        echo "</select>";
        echo "</td>";

        echo "<td width='150' valign='top'>";
        echo "<select name='subject_matter'>";
        foreach ($sj as $s) {
            $optionId = $s["id"];
            $optionLabel = $s["subject_matter"];

            if($assign == $optionId){ $selected="selected"; } else {$selected="";}

            echo "<option value='$optionId' $selected>$optionLabel</option>";

            //echo $selected. " ".$row["assignment"]. " " .$editor["editorname"]. " ". $editor["id"] ."<br>";

        }
        echo "</select>";
        echo "</td>";
        echo "<td valign='top'>";
        echo "<input type='submit' value='Update'>";
        echo "</form>";
        echo "</td>";
        echo "</tr>";
    }
    echo "</table>";
    echo "A total of ". mysqli_num_rows($result)." records were returned.<br>";
} else {
    echo "No data found.";
}



// Close
?>
