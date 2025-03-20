<?php
//include("index.html");
//$nav=3;

// Connect to the MySQL database
$conn = mysqli_connect('localhost','MSBABlog','44C#atlantic','MSBABlog');

// Check the connection
if (!$conn) {
    die("Connection failed: " . mysqli_connect_error());
}

// Retrieve data from the database
$sql = "SELECT id, citation, snippet, filed_date, parties, date_added, reviewed, assignment, court, URL, NotesOnAssignment, Entry_Posted FROM tbscrapedata where snippet is not null and assignment<>23 and reviewed=1 and entry_posted<>1 order by date_added DESC;";
$result = mysqli_query($conn, $sql);

$sql="select id, editorname, editoremail from editors where editorstatus='Active' order by editorname;";
$editors = mysqli_query($conn, $sql);

// Build the HTML table
if (mysqli_num_rows($result) > 0) {
    echo "<table><thead>";
    echo "<tr align='center'>";
    echo "<th valign='center'>Case</th>";
    echo "<th valign='center'>Cite</th>";
    echo "<th valign='center'>Snippet</th>";
    echo "<th valign='center'>Assigned Editor</th>";
    echo "<th valign='center'>Notes on Assignment</th>";
    echo "<th valign='center'>Entry Posted</th>";
    echo "</tr></thead>";

    while ($row = mysqli_fetch_assoc($result)) {
        $assign=$row["assignment"];
        $entry=$row["Entry_Posted"];
        $notes=$row["NotesOnAssignment"];

        if($entry==1) {
          $check="checked";
        } else {
          $check="unchecked";
        }

        echo "<tr>";
        echo "<td valign='center'><a href='" . $row["URL"] . "' target='_blank'>" . $row["parties"] . "</a></td>";
        echo "<td valign='center'>" . $row["citation"] . "</td>";
        echo "<td valign='center'>" . $row["snippet"] . "</td>";

        // Add more columns as needed

        // Form for updating data
        echo "<td width='150' valign='center'>";
        echo "<form method='POST' action='index.php'>";
        echo "<input type='hidden' name='record_id' value='" . $row["id"] . "'>";
        echo "<input type='hidden' name='nav' value='30'>";
        echo "<select name='editorvalue'>";
        foreach ($editors as $editor) {
            $optionId = $editor["id"];
            $optionLabel = $editor["editorname"];

            if($assign == $optionId){ $selected="selected"; } else {$selected="";}

            echo "<option value='$optionId' $selected>$optionLabel</option>";

        }
        echo "</select>";
        echo "</td>";
        echo "<td>";
        echo "<input type='text' id='NotesOnAssignment' name='NotesOnAssignment' value='$notes'>";
        echo "</td>";
        echo "<td>";
        echo "<input type='checkbox' id='Entry_Posted' name='Entry_Posted' $check>";
        echo "</td>";
        echo "<td valign='center'>";
        echo "<input type='submit' value='Update'>";
        echo "</form>";
        echo "</td>";
        echo "</tr>";
    }
    echo "</table>";
    echo "<p class='footer'>A total of ". mysqli_num_rows($result)." records were returned.<br>";
} else {
    echo "<p class='footer'>No data found.";
}



// Close
?>
